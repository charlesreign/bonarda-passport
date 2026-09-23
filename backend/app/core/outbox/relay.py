import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

import asyncpg
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.outbox.models import OutboxEvent
from app.core.outbox.registry import HandlerRegistry
from app.core.outbox.writer import OUTBOX_CHANNEL
from app.core.time import utcnow

HANDLER_JOB = "run_event_handler"
BATCH_SIZE = 100
STUCK_AFTER_ATTEMPTS = 10
BACKOFF_INITIAL_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0

Enqueue = Callable[..., Awaitable[object]]
log = structlog.get_logger(__name__)

# Module-level alias so tests can patch just this call site (e.g. to simulate
# Postgres being unreachable) without touching the shared `asyncpg` module,
# which SQLAlchemy's asyncpg dialect also imports for the sessionmaker's own
# connections.
_connect = asyncpg.connect


def listen_dsn(database_url: str) -> str:
    """asyncpg.connect() needs a plain postgresql:// DSN."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def next_backoff(current: float) -> float:
    """Capped exponential backoff: 0 (not backing off) -> 1s, then doubles each
    consecutive call, capped at BACKOFF_CAP_SECONDS. Callers reset to 0 after a
    fully successful pass."""
    if current <= 0:
        return BACKOFF_INITIAL_SECONDS
    return min(current * 2, BACKOFF_CAP_SECONDS)


async def _relay_once_detailed(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
) -> tuple[int, int]:
    """Claims a batch of undispatched events (SKIP LOCKED, so several relays can
    run) and enqueues one Arq job per handler. The job ID makes re-enqueueing
    after a partial failure harmless. Returns (claimed, dispatched)."""
    dispatched = 0
    async with sessionmaker() as session, session.begin():
        rows = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.dispatched_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            try:
                for name in registry.handler_names_for(row.event_type):
                    await enqueue(
                        HANDLER_JOB, str(row.event_id), name, _job_id=f"{row.event_id}:{name}"
                    )
            except Exception:
                row.attempts += 1
                level = log.error if row.attempts >= STUCK_AFTER_ATTEMPTS else log.warning
                level(
                    "outbox.enqueue_failed",
                    event_id=str(row.event_id),
                    event_type=row.event_type,
                    attempts=row.attempts,
                    exc_info=True,
                )
                continue
            row.dispatched_at = utcnow()
            dispatched += 1
    return len(rows), dispatched


async def relay_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
) -> int:
    """Runs one claim-and-dispatch pass. Returns the number of rows
    successfully dispatched (rows whose dispatched_at was set) — NOT the
    number claimed, so a pass where every enqueue failed (e.g. Redis is down)
    returns 0 rather than the batch size. `run_relay` uses that to back off
    instead of spinning."""
    _claimed, dispatched = await _relay_once_detailed(sessionmaker, registry, enqueue)
    return dispatched


async def run_relay(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
    *,
    listen_dsn: str,
    stop: asyncio.Event,
    poll_interval: float = 2.0,
) -> None:
    """Wakes on NOTIFY outbox (immediate) or every poll_interval (fallback).

    Resilient to both dependencies being unavailable:
    - Postgres (the LISTEN connection): connecting is retried with capped
      backoff instead of raising out of the task at startup (which would kill
      it silently) or wherever the connection later drops. While
      disconnected, relay_once still runs on poll_interval — NOTIFY is only a
      latency optimization, the poll loop is the source of truth.
    - Redis (the enqueue target, via `enqueue`): a pass where any enqueue
      failed backs off with the same capped-exponential wait instead of
      looping immediately, which is what let `attempts` blow past
      STUCK_AFTER_ATTEMPTS in milliseconds before this fix.
    """
    wake = asyncio.Event()
    conn: asyncpg.Connection | None = None
    listen_backoff = 0.0
    next_listen_attempt = 0.0
    dispatch_backoff = 0.0

    async def try_listen() -> asyncpg.Connection | None:
        try:
            new_conn = await _connect(listen_dsn)
            await new_conn.add_listener(OUTBOX_CHANNEL, lambda *_: wake.set())
        except Exception:
            log.warning("outbox.relay_listen_unavailable", exc_info=True)
            return None
        return new_conn

    try:
        while not stop.is_set():
            now = time.monotonic()
            if (conn is None or conn.is_closed()) and now >= next_listen_attempt:
                conn = await try_listen()
                if conn is None:
                    listen_backoff = next_backoff(listen_backoff)
                    next_listen_attempt = now + listen_backoff
                else:
                    listen_backoff = 0.0

            wake.clear()
            try:
                claimed, dispatched = await _relay_once_detailed(sessionmaker, registry, enqueue)
            except Exception:
                log.exception("outbox.relay_failed")
                claimed, dispatched = 0, 0

            if dispatched == BATCH_SIZE:
                dispatch_backoff = 0.0
                continue
            if dispatched < claimed:
                dispatch_backoff = next_backoff(dispatch_backoff)
                wait = dispatch_backoff
            else:
                dispatch_backoff = 0.0
                wait = poll_interval
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=wait)
    finally:
        if conn is not None and not conn.is_closed():
            await conn.close()

import asyncio
import contextlib
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

Enqueue = Callable[..., Awaitable[object]]
log = structlog.get_logger(__name__)


def listen_dsn(database_url: str) -> str:
    """asyncpg.connect() needs a plain postgresql:// DSN."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def relay_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
) -> int:
    """Claims a batch of undispatched events (SKIP LOCKED, so several relays can
    run) and enqueues one Arq job per handler. The job ID makes re-enqueueing
    after a partial failure harmless. Returns the number of rows claimed."""
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
    return len(rows)


async def run_relay(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
    *,
    listen_dsn: str,
    stop: asyncio.Event,
    poll_interval: float = 2.0,
) -> None:
    """Wakes on NOTIFY outbox (immediate) or every poll_interval (fallback)."""
    wake = asyncio.Event()
    conn = await asyncpg.connect(listen_dsn)
    await conn.add_listener(OUTBOX_CHANNEL, lambda *_: wake.set())
    try:
        while not stop.is_set():
            wake.clear()
            try:
                claimed = await relay_once(sessionmaker, registry, enqueue)
            except Exception:
                log.exception("outbox.relay_failed")
                claimed = 0
            if claimed == BATCH_SIZE:
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=poll_interval)
    finally:
        await conn.close()

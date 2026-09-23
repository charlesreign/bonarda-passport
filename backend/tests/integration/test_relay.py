import asyncio
from datetime import timedelta
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.outbox.events import DomainEvent
from app.core.outbox.models import OutboxEvent, ProcessedEvent
from app.core.outbox.processing import process_event, purge_dispatched_events
from app.core.outbox.registry import HandlerRegistry
from app.core.outbox.relay import HANDLER_JOB, STUCK_AFTER_ATTEMPTS, relay_once, run_relay
from app.core.outbox.writer import emit_event
from app.core.time import utcnow


class WorkerPinged(DomainEvent):
    event_type: ClassVar[str] = "test.worker_pinged"
    note: str


class FakeEnqueue:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.fail = fail

    async def __call__(self, job: str, event_id: str, handler: str, *, _job_id: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.calls.append((job, event_id, handler, _job_id))


async def _noop(session: AsyncSession, payload: dict[str, Any]) -> None:
    return None


async def _emit(sm: async_sessionmaker[AsyncSession], note: str = "hi") -> UUID:
    async with sm() as s, s.begin():
        row = await emit_event(s, WorkerPinged(aggregate_id=uuid4(), note=note))
    return row.event_id


@pytest.fixture
def registry() -> HandlerRegistry:
    r = HandlerRegistry()
    r.register(WorkerPinged, "roster.refresh", _noop)
    r.register(WorkerPinged, "notify.worker", _noop)
    return r


async def test_relay_enqueues_every_handler_with_deterministic_job_id(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    event_id = await _emit(sessionmaker)
    enqueue = FakeEnqueue()

    dispatched = await relay_once(sessionmaker, registry, enqueue)

    assert dispatched == 1
    assert enqueue.calls == [
        (HANDLER_JOB, str(event_id), "roster.refresh", f"{event_id}:roster.refresh"),
        (HANDLER_JOB, str(event_id), "notify.worker", f"{event_id}:notify.worker"),
    ]
    async with sessionmaker() as s:
        row = (await s.scalars(select(OutboxEvent))).one()
    assert row.dispatched_at is not None


async def test_relay_marks_events_without_handlers_dispatched(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _emit(sessionmaker)

    await relay_once(sessionmaker, HandlerRegistry(), FakeEnqueue())

    async with sessionmaker() as s:
        row = (await s.scalars(select(OutboxEvent))).one()
    assert row.dispatched_at is not None


async def test_relay_skips_already_dispatched_events(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    await _emit(sessionmaker)
    await relay_once(sessionmaker, registry, FakeEnqueue())
    second = FakeEnqueue()

    assert await relay_once(sessionmaker, registry, second) == 0
    assert second.calls == []


async def test_relay_keeps_event_pending_and_counts_attempts_when_enqueue_fails(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    await _emit(sessionmaker)

    await relay_once(sessionmaker, registry, FakeEnqueue(fail=True))
    await relay_once(sessionmaker, registry, FakeEnqueue(fail=True))

    async with sessionmaker() as s:
        row = (await s.scalars(select(OutboxEvent))).one()
    assert row.dispatched_at is None
    assert row.attempts == 2
    assert STUCK_AFTER_ATTEMPTS == 10


async def test_relay_once_returns_zero_dispatched_when_every_enqueue_fails(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    """With Redis down, a pass must report 0 dispatched (not the claimed batch
    size) so run_relay can tell the difference and back off instead of
    spinning — see test_run_relay_survives_listen_connect_failure and
    next_backoff in tests/unit/test_outbox_relay.py."""
    for i in range(3):
        await _emit(sessionmaker, note=f"e{i}")

    dispatched = await relay_once(sessionmaker, registry, FakeEnqueue(fail=True))

    assert dispatched == 0
    async with sessionmaker() as s:
        rows = (await s.scalars(select(OutboxEvent))).all()
    assert len(rows) == 3
    assert all(row.dispatched_at is None and row.attempts == 1 for row in rows)


async def test_run_relay_survives_listen_connect_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """asyncpg.connect() failing (Postgres unreachable at worker startup, or
    the LISTEN connection later dropping) must not end the relay task: it
    keeps dispatching via the poll_interval fallback instead of NOTIFY."""
    event_id = await _emit(sessionmaker)
    enqueue = FakeEnqueue()

    async def always_fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr("app.core.outbox.relay._connect", always_fail)
    stop = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    stopper = asyncio.create_task(_stop_soon())
    await run_relay(
        sessionmaker,
        registry,
        enqueue,
        listen_dsn="postgresql://unused/unused",
        stop=stop,
        poll_interval=0.01,
    )
    await stopper

    assert enqueue.calls  # dispatched via the poll loop, not LISTEN
    assert enqueue.calls[0][1] == str(event_id)


async def test_process_event_runs_handler_exactly_once(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seen: list[dict[str, Any]] = []

    async def record(session: AsyncSession, payload: dict[str, Any]) -> None:
        seen.append(payload)

    registry = HandlerRegistry()
    registry.register(WorkerPinged, "test.record", record)
    event_id = await _emit(sessionmaker, note="once")

    first = await process_event(sessionmaker, registry, event_id, "test.record")
    second = await process_event(sessionmaker, registry, event_id, "test.record")

    assert (first, second) == (True, False)
    assert [p["note"] for p in seen] == ["once"]


async def test_failed_handler_releases_its_claim_for_retry(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    calls = 0

    async def flaky(session: AsyncSession, payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider timeout")

    registry = HandlerRegistry()
    registry.register(WorkerPinged, "test.flaky", flaky)
    event_id = await _emit(sessionmaker)

    with pytest.raises(RuntimeError):
        await process_event(sessionmaker, registry, event_id, "test.flaky")
    assert await process_event(sessionmaker, registry, event_id, "test.flaky") is True
    assert calls == 2


async def test_purge_removes_only_old_dispatched_events(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    old_id = await _emit(sessionmaker, note="old")
    await _emit(sessionmaker, note="pending")
    async with sessionmaker() as s, s.begin():
        await s.execute(
            update(OutboxEvent)
            .where(OutboxEvent.event_id == old_id)
            .values(dispatched_at=utcnow() - timedelta(days=15))
        )
        s.add(
            ProcessedEvent(event_id=old_id, handler="x", processed_at=utcnow() - timedelta(days=15))
        )

    purged = await purge_dispatched_events(sessionmaker, older_than=timedelta(days=14))

    assert purged == 1
    async with sessionmaker() as s:
        remaining = (await s.scalars(select(OutboxEvent.payload))).all()
        processed = await s.scalar(select(func.count()).select_from(ProcessedEvent))
    assert [p["note"] for p in remaining] == ["pending"]
    assert processed == 0

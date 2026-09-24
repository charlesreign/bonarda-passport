from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import get_event_id
from app.core.outbox.events import DomainEvent
from app.core.outbox.processing import process_event
from app.core.outbox.registry import HandlerRegistry
from app.core.outbox.writer import emit_event


class _Ping(DomainEvent):
    event_type: ClassVar[str] = "test.ping"


async def test_handlers_see_the_event_they_are_processing(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seen: list[UUID | None] = []

    async def handler(session: AsyncSession, payload: dict[str, Any]) -> None:
        seen.append(get_event_id())

    registry = HandlerRegistry()
    registry.register(_Ping, "test.record_event_id", handler)
    async with sessionmaker() as session, session.begin():
        row = await emit_event(session, _Ping(aggregate_id=uuid4()))
        await session.flush()
        event_id = row.event_id

    await process_event(sessionmaker, registry, event_id, "test.record_event_id")

    assert seen == [event_id]
    assert get_event_id() is None

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import correlation_scope
from app.core.outbox.models import OutboxEvent, ProcessedEvent
from app.core.outbox.registry import HandlerRegistry
from app.core.time import utcnow


async def process_event(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    event_id: UUID,
    handler_name: str,
) -> bool:
    """Runs one handler for one event, at most once. The claim row and the
    handler's writes share a transaction: if the handler raises, both roll back
    and a retry runs it again. Returns False if it already ran."""
    async with sessionmaker() as session, session.begin():
        claimed = await session.scalar(
            pg_insert(ProcessedEvent)
            .values(event_id=event_id, handler=handler_name)
            .on_conflict_do_nothing()
            .returning(ProcessedEvent.event_id)
        )
        if claimed is None:
            return False
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id))
        if event is None:
            raise LookupError(f"outbox event {event_id} not found")
        with correlation_scope(event.correlation_id):
            await registry.get(handler_name)(session, event.payload)
    return True


async def purge_dispatched_events(
    sessionmaker: async_sessionmaker[AsyncSession], *, older_than: timedelta
) -> int:
    cutoff = utcnow() - older_than
    async with sessionmaker() as session, session.begin():
        result = await session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.dispatched_at.is_not(None), OutboxEvent.dispatched_at < cutoff
            )
        )
        await session.execute(delete(ProcessedEvent).where(ProcessedEvent.processed_at < cutoff))
    return result.rowcount

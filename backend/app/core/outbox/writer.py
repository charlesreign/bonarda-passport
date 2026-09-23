from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_correlation_id
from app.core.outbox.events import DomainEvent
from app.core.outbox.models import OutboxEvent

OUTBOX_CHANNEL = "outbox"


async def emit_event(session: AsyncSession, event: DomainEvent) -> OutboxEvent:
    """Adds the event to the caller's transaction. Postgres delivers the NOTIFY
    only if that transaction commits, so the relay never sees a rolled-back event."""
    row = OutboxEvent(
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        payload=event.model_dump(mode="json"),
        correlation_id=get_correlation_id(),
    )
    session.add(row)
    await session.execute(text("SELECT pg_notify(:channel, '')"), {"channel": OUTBOX_CHANNEL})
    return row

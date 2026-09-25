"""The one way an engagement becomes `cancelled`, so every cancellation
records its cause (and a decline its time) and emits the same events."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.enums import DECLINE_CAUSES, CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.schemas import EngagementCancelled, EngagementDeclined


async def cancel(
    session: AsyncSession,
    engagement: Engagement,
    cause: CancelCause,
    *,
    actor: Actor | None,
    action: str,
    reason: str | None = None,
    after: Mapping[str, Any] | None = None,
) -> None:
    """Callers lock the row first. A worker decline sets `decline_reason`
    (and any note) before calling, so the row is valid when it flushes."""
    declined = cause in DECLINE_CAUSES
    engagement.status = EngagementStatus.CANCELLED
    engagement.cancel_cause = cause
    engagement.stuck_flagged_at = None
    if declined:
        engagement.declined_at = utcnow()
    await write_audit(
        session,
        actor=actor,
        action=action,
        target_type="engagement",
        target_id=engagement.id,
        after=after,
        reason=reason,
    )
    await emit_event(
        session,
        EngagementCancelled(
            aggregate_id=engagement.id,
            worker_id=engagement.worker_id,
            project_id=engagement.project_id,
            cause=cause,
        ),
    )
    if declined:
        await emit_event(
            session,
            EngagementDeclined(
                aggregate_id=engagement.id,
                worker_id=engagement.worker_id,
                project_id=engagement.project_id,
                cause=cause,
            ),
        )

from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.time import utcnow
from app.modules.engagements.repository import EngagementRepository

log = structlog.get_logger(__name__)


async def flag_stuck(session: AsyncSession, settings: Settings) -> int:
    """Every 15 minutes: make contracts that stalled visible to the PM
    (`stuck: true`, retry action) and to engineering (warning log)."""
    now = utcnow()
    stuck = await EngagementRepository(session).stuck_candidates(
        pending_before=now - timedelta(minutes=settings.stuck_pending_minutes),
        awaiting_before=now - timedelta(hours=settings.stuck_awaiting_hours),
    )
    for engagement in stuck:
        engagement.stuck_flagged_at = now
        await write_audit(
            session,
            actor=None,
            action="engagement.flagged_stuck",
            target_type="engagement",
            target_id=engagement.id,
            after={"status": engagement.status.value},
        )
        log.warning(
            "engagements.stuck",
            engagement_id=str(engagement.id),
            status=engagement.status.value,
        )
    return len(stuck)

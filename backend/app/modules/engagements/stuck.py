from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import PayrollSignalRequested

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


async def retry_payroll_signals(session: AsyncSession, settings: Settings) -> int:
    """Every 15 minutes (with `flag_stuck`): an activated engagement whose
    payroll signal was lost (dead-lettered handler) gets `PayrollSignalRequested`
    emitted. That event is wired only to the payroll-signal handler, not to
    `EngagementActivated`'s mail handlers, so a retry never re-mails the
    worker or PMs — even across many runs while the signal stays lost."""
    now = utcnow()
    lost = await EngagementRepository(session).payroll_unsignalled(
        billable_before=now - timedelta(minutes=settings.payroll_signal_grace_minutes)
    )
    for engagement in lost:
        await write_audit(
            session,
            actor=None,
            action="engagement.payroll_signal_retried",
            target_type="engagement",
            target_id=engagement.id,
        )
        await emit_event(session, PayrollSignalRequested(aggregate_id=engagement.id))
        log.warning("engagements.payroll_signal_retried", engagement_id=str(engagement.id))
    return len(lost)

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.repository import EngagementRepository
from app.modules.integrations.service import PayrollActivation, PayrollAdapter


async def signal_payroll(
    session: AsyncSession, payroll: PayrollAdapter, engagement_id: UUID
) -> None:
    """Outbox handler (FR-8.3): once per engagement."""
    engagement = await EngagementRepository(session).get_for_update(engagement_id)
    if (
        engagement is None
        or engagement.status is not EngagementStatus.ACTIVE
        or engagement.payroll_signaled_at is not None
    ):
        return
    await payroll.signal_active(
        PayrollActivation(
            engagement_id=engagement.id,
            worker_id=engagement.worker_id,
            start_date=engagement.start_date,
            rate=engagement.rate,
            currency=engagement.currency,
        )
    )
    engagement.payroll_signaled_at = utcnow()
    await write_audit(
        session,
        actor=None,
        action="engagement.payroll_signaled",
        target_type="engagement",
        target_id=engagement.id,
    )

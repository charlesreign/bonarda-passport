"""The daily dispute SLA digest to People Ops (spec §7.7 dispute_sla_reminder)."""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.governance.models import Dispute
from app.modules.governance.repository import DisputeRepository
from app.modules.identity.service import staff_contacts


def _line(dispute: Dispute, now: datetime, locale: str) -> str:
    state = t("dispute_sla.overdue" if dispute.due_at <= now else "dispute_sla.due_soon", locale)
    return f"- {dispute.id}: {state} ({dispute.due_at.date().isoformat()})"


async def remind_due_disputes(
    session: AsyncSession, mailer: Mailer, *, now: datetime, warn_days: int
) -> int:
    """Mails every active People Ops account one digest of the open disputes
    that are overdue or due within `warn_days`. Returns how many it listed."""
    due = await DisputeRepository(session).open_due_before(now + timedelta(days=warn_days))
    if not due:
        return 0
    overdue = sum(1 for dispute in due if dispute.due_at <= now)
    for contact in await staff_contacts(session, UserRole.PEOPLE_OPS):
        await mailer.send(
            to=contact.email,
            subject=t(
                "dispute_sla.subject", contact.locale, overdue=overdue, due_soon=len(due) - overdue
            ),
            body=t(
                "dispute_sla.body",
                contact.locale,
                lines="\n".join(_line(dispute, now, contact.locale) for dispute in due),
            ),
        )
    return len(due)

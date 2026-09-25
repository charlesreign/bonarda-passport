"""Tells a worker how their dispute ended (spec §7.7 DisputeResolved → notify_worker).
The notes come from the dispute row: outbox payloads carry no free text."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.governance.repository import DisputeRepository
from app.modules.identity.service import staff_contacts, worker_contact


async def notify_dispute_resolved(session: AsyncSession, mailer: Mailer, dispute_id: UUID) -> bool:
    dispute = await DisputeRepository(session).get(dispute_id)
    if dispute is None or dispute.resolution is None:
        return False
    contact = await worker_contact(session, dispute.worker_id)
    if contact is None:
        return False
    await mailer.send(
        to=contact.email,
        subject=t("dispute_resolved.subject", contact.locale),
        body=t(
            f"dispute_resolved.body.{dispute.resolution.value}",
            contact.locale,
            notes=dispute.resolution_notes or "",
        ),
    )
    return True


async def notify_concentration_alert(
    session: AsyncSession, mailer: Mailer, *, scope: str, share: float, alert_share: float
) -> int:
    """Tells every active People Ops account (NFR-5.3). Returns how many."""
    contacts = await staff_contacts(session, UserRole.PEOPLE_OPS)
    for contact in contacts:
        await mailer.send(
            to=contact.email,
            subject=t("concentration_alert.subject", contact.locale, scope=scope),
            body=t(
                "concentration_alert.body",
                contact.locale,
                scope=scope,
                share=f"{share:.0%}",
                threshold=f"{alert_share:.0%}",
            ),
        )
    return len(contacts)

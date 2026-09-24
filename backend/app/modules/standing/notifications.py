"""Tells a worker their tier changed (spec §7.7 notify_worker on StandingChanged)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.identity.service import worker_contact


async def notify_standing_changed(
    session: AsyncSession, mailer: Mailer, worker_id: UUID, *, previous: str, new: str
) -> bool:
    contact = await worker_contact(session, worker_id)
    if contact is None:
        return False
    locale = contact.locale
    await mailer.send(
        to=contact.email,
        subject=t("standing_changed.subject", locale),
        body=t(
            "standing_changed.body",
            locale,
            previous=t(f"tier.{previous}", locale),
            tier=t(f"tier.{new}", locale),
        ),
    )
    return True

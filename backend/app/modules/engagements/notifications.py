"""Mail the engagements module sends (spec §7.7 notify_worker, notify_feedback_due).
Recipients without an account are skipped: the event must never dead-letter."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.identity.service import account_contact, active_pm_ids, worker_contact
from app.modules.passport.service import worker_name


async def notify_engagement_confirmed(
    session: AsyncSession, mailer: Mailer, engagement_id: UUID
) -> bool:
    """To the worker once their engagement is active. False if nobody was
    told, including when the engagement has since moved past ACTIVE (a
    payroll-signal retry re-runs the payroll handler, not this one, but this
    guard keeps the handler itself safe against any late/duplicate call)."""
    engagement = await EngagementRepository(session).get(engagement_id)
    if engagement is None or engagement.status is not EngagementStatus.ACTIVE:
        return False
    contact = await worker_contact(session, engagement.worker_id)
    project = await ProjectRepository(session).get(engagement.project_id)
    if contact is None or project is None:
        return False
    await mailer.send(
        to=contact.email,
        subject=t("engagement_confirmed.subject", contact.locale, project=project.name),
        body=t(
            "engagement_confirmed.body",
            contact.locale,
            project=project.name,
            start_date=engagement.start_date.isoformat(),
        ),
    )
    return True


async def notify_feedback_due(session: AsyncSession, mailer: Mailer, engagement_id: UUID) -> int:
    """To every active PM staffed on the project, unless feedback is already
    in. Returns how many PMs were told."""
    engagements = EngagementRepository(session)
    engagement = await engagements.get(engagement_id)
    if engagement is None or engagement.id in await engagements.feedback_for([engagement.id]):
        return 0
    projects = ProjectRepository(session)
    project = await projects.get(engagement.project_id)
    if project is None:
        return 0
    name = await worker_name(session, engagement.worker_id) or ""
    pm_ids = await active_pm_ids(session, await projects.active_staff_ids(project.id))
    for user_id in sorted(pm_ids, key=str):
        contact = await account_contact(session, user_id)
        await mailer.send(
            to=contact.email,
            subject=t("feedback_due.subject", contact.locale, worker=name, project=project.name),
            body=t("feedback_due.body", contact.locale, worker=name, project=project.name),
        )
    return len(pm_ids)

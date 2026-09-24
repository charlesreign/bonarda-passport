from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.time import utcnow
from app.modules.engagements.contracts import activate_due
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.notifications import notify_feedback_due
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import WorkerType
from app.modules.passport.models import Worker
from app.modules.standing.recalculation import recalculate
from tests.support import (
    RecordingMailer,
    bearer,
    make_dispute,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

Drain = Callable[[], Awaitable[None]]


async def _start_today(session: AsyncSession, worker_id: UUID, project_id: UUID) -> None:
    engagement = await make_engagement(
        session,
        worker_id=worker_id,
        project_id=project_id,
        status=EngagementStatus.SIGNED,
        start_date=utcnow().date(),
    )
    engagement.signed_at = utcnow()
    await session.commit()
    assert await activate_due(session) == 1
    await session.commit()


async def test_the_worker_hears_when_their_engagement_starts(
    session: AsyncSession, drain: Drain, mailer: RecordingMailer
) -> None:
    worker, _ = await make_worker(session, email="kofi@example.com", locale="fr")
    project = await make_project(session, name="Projet Volta")

    await _start_today(session, worker.id, project.id)
    await drain()

    (mail,) = (m for m in mailer.sent if m["to"] == "kofi@example.com")
    assert mail["subject"] == "Votre mission sur Projet Volta a commencé"
    assert utcnow().date().isoformat() in mail["body"]


async def test_a_worker_without_an_account_gets_no_mail_and_no_error(
    session: AsyncSession, drain: Drain, mailer: RecordingMailer
) -> None:
    worker = Worker(full_name="No Account", worker_type=WorkerType.FREELANCER, data_region="GH")
    session.add(worker)
    await session.flush()
    project = await make_project(session)

    await _start_today(session, worker.id, project.id)
    await drain()

    assert mailer.sent == []


async def test_staffed_pms_hear_that_feedback_is_due(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    ama = await make_user(session, role=UserRole.PM, email="ama@bonarda.works")
    gone = await make_user(
        session, role=UserRole.PM, email="gone@bonarda.works", status=AccountStatus.REVOKED
    )
    worker, _ = await make_worker(session, full_name="Kofi Mensah")
    project = await make_project(session, staff=[ama, gone], name="Project Volta")
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        status=EngagementStatus.ACTIVE,
        start_date=utcnow().date() - timedelta(days=30),
    )

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, ama)
    )
    await drain()

    assert response.status_code == 200
    due = [m for m in mailer.sent if m["subject"].startswith("Feedback due")]
    assert [m["to"] for m in due] == ["ama@bonarda.works"]
    assert due[0]["subject"] == "Feedback due for Kofi Mensah on Project Volta"


async def test_no_feedback_reminder_once_feedback_is_in(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session)
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    mailer = RecordingMailer()

    assert await notify_feedback_due(session, mailer, engagement.id) == 0
    assert mailer.sent == []


async def test_the_worker_hears_when_their_standing_changes(
    session: AsyncSession, drain: Drain, mailer: RecordingMailer
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session, email="kofi@example.com", locale="fr")
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()
    await drain()

    (mail,) = (m for m in mailer.sent if m["to"] == "kofi@example.com")
    assert mail["subject"] == "Votre statut Bonarda a changé"
    assert "Non classé" in mail["body"]
    assert "Niveau 1" in mail["body"]


async def test_the_worker_hears_how_their_dispute_ended(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    worker, _ = await make_worker(session, email="kofi@example.com")
    dispute = await make_dispute(session, worker_id=worker.id, due_at=utcnow() + timedelta(days=30))
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    notes = "The feedback was written for a different engagement."

    response = await client.patch(
        f"/api/v1/disputes/{dispute.id}",
        json={"resolution": "rejected", "resolution_notes": notes},
        headers=bearer(settings, ops),
    )
    await drain()

    assert response.status_code == 200
    (mail,) = (m for m in mailer.sent if m["to"] == "kofi@example.com")
    assert mail["subject"] == "Your dispute has been resolved"
    assert "did not uphold" in mail["body"]
    assert notes in mail["body"]

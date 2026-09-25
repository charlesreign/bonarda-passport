from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement, ProjectStaff
from app.modules.engagements.notifications import notify_offer_declined
from tests.support import (
    RecordingMailer,
    bearer,
    engagement_terms,
    esign_webhook,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def test_each_staffed_pm_is_told_in_their_language(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    english = await make_user(session, role=UserRole.PM, email="efua@example.com")
    french = await make_user(session, role=UserRole.PM, email="luc@example.com", locale="fr")
    departed = await make_user(session, role=UserRole.PM, email="gone@example.com")
    project = await make_project(session, staff=[english, french, departed])
    await session.execute(  # the departed PM has left the project's staff
        update(ProjectStaff)
        .where(ProjectStaff.user_account_id == departed.id)
        .values(active_to=utcnow())
    )
    await session.commit()
    worker, account = await make_ready_worker(session, full_name="Ama Owusu")
    offer = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, english),
    )
    await client.post(
        f"/api/v1/workers/me/engagements/{offer.json()['id']}/decline",
        json={"reason": "dates", "note": "Busy that month"},
        headers=bearer(settings, account),
    )
    mailer.sent.clear()

    await drain()

    by_recipient = {m["to"]: m for m in mailer.sent}
    assert set(by_recipient) == {"efua@example.com", "luc@example.com"}
    assert by_recipient["efua@example.com"]["subject"] == (
        "Ama Owusu declined the offer on Project Volta"
    )
    assert "Reason: Dates" in by_recipient["efua@example.com"]["body"]
    assert "Busy that month" in by_recipient["efua@example.com"]["body"]
    assert by_recipient["luc@example.com"]["subject"] == (
        "Ama Owusu a refusé l'offre pour Project Volta"
    )


async def test_a_provider_decline_is_announced_without_a_reason(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    pm = await make_user(session, role=UserRole.PM, email="efua@example.com")
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session, full_name="Ama Owusu")
    offer = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )
    await drain()
    row = await session.get(Engagement, offer.json()["id"])
    assert row is not None
    await session.refresh(row)
    body, headers = esign_webhook(
        settings, {"envelope_id": row.esign_envelope_id, "event": "declined"}
    )
    await client.post("/api/v1/webhooks/esign", content=body, headers=headers)
    mailer.sent.clear()

    await drain()

    assert [m["to"] for m in mailer.sent] == ["efua@example.com"]
    assert "No reason was given" in mailer.sent[0]["body"]


async def test_nobody_to_tell_is_not_an_error(session: AsyncSession) -> None:
    worker, _ = await make_ready_worker(session)
    project = await make_project(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.WORKER_DECLINED,
    )
    mailer = RecordingMailer()

    assert await notify_offer_declined(session, mailer, engagement.id) == 0
    assert mailer.sent == []

import json
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import WorkerStatus
from app.modules.passport.models import Skill, Worker
from tests.support import bearer, make_engagement, make_project, make_ready_worker, make_user

Drain = Callable[[], Awaitable[None]]
ANSWERS = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": False,
    "would_reengage": True,
}


async def _active(session: AsyncSession) -> tuple[UserAccount, Worker, Engagement]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, account = await make_ready_worker(session)
    worker.status = WorkerStatus.ACTIVE
    await session.commit()
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.ACTIVE
    )
    return pm, worker, engagement


async def test_completing_the_last_active_engagement_makes_the_worker_dormant(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _active(session)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, pm)
    )
    await drain()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["end_date"] == utcnow().date().isoformat()
    await session.refresh(worker)
    assert (worker.status, worker.dormant_since) == (WorkerStatus.DORMANT, utcnow().date())


async def test_worker_with_another_active_engagement_stays_active(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _active(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Other")).id,
        status=EngagementStatus.ACTIVE,
    )

    await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, pm)
    )
    await drain()

    await session.refresh(worker)
    assert worker.status is WorkerStatus.ACTIVE


async def test_only_active_engagements_complete(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, worker, _ = await _active(session)
    signed = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="Signed")).id,
        status=EngagementStatus.SIGNED,
    )

    response = await client.post(
        f"/api/v1/engagements/{signed.id}/complete", json={}, headers=bearer(settings, pm)
    )

    assert response.json()["code"] == "engagement_not_active"


async def test_feedback_is_recorded_published_and_visible_to_the_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, worker, engagement = await _active(session)
    skill = await session.scalar(select(Skill))
    assert skill is not None
    await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, pm)
    )

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={
            "structured_answers": ANSWERS,
            "free_text": "Reliable; flagged risks early.",
            "skill_ids_demonstrated": [str(skill.id)] * 2,
        },
        headers=bearer(settings, pm),
    )

    assert response.status_code == 201
    feedback = response.json()["feedback"]
    assert feedback["skill_ids_demonstrated"] == [str(skill.id)]
    event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "engagements.feedback_submitted")
        )
    ).one()
    assert event.payload["reviewer_id"] == str(pm.id)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "feedback.submitted"))
    ).one()
    assert "Reliable" not in json.dumps([audit.before, audit.after])
    history = await client.get(
        f"/api/v1/workers/{worker.id}/engagements",
        headers=bearer(settings, await _account_of(session, worker)),
    )
    assert history.json()[0]["feedback"]["free_text"] == "Reliable; flagged risks early."


async def _account_of(session: AsyncSession, worker: Worker) -> UserAccount:
    return (
        await session.scalars(select(UserAccount).where(UserAccount.worker_id == worker.id))
    ).one()


async def test_feedback_rules(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, _, engagement = await _active(session)
    url = f"/api/v1/engagements/{engagement.id}/feedback"
    headers = bearer(settings, pm)

    too_early = await client.post(url, json={"structured_answers": ANSWERS}, headers=headers)
    await client.post(f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=headers)
    unclaimed = await client.post(
        url,
        json={"structured_answers": ANSWERS, "skill_ids_demonstrated": [str(uuid4())]},
        headers=headers,
    )
    first = await client.post(url, json={"structured_answers": ANSWERS}, headers=headers)
    duplicate = await client.post(url, json={"structured_answers": ANSWERS}, headers=headers)

    assert too_early.json()["code"] == "engagement_not_completed"
    assert unclaimed.json()["code"] == "skill_not_claimed"
    assert first.status_code == 201
    assert duplicate.json()["code"] == "feedback_exists"


@pytest.mark.parametrize(
    "answers",
    [
        {"delivered_on_agreed_dates": True, "would_reengage": True},
        ANSWERS | {"mood": True},
    ],
)
async def test_structured_answers_must_be_exactly_the_three_questions(
    client: AsyncClient, session: AsyncSession, settings: Settings, answers: dict[str, bool]
) -> None:
    pm, _, engagement = await _active(session)
    headers = bearer(settings, pm)
    await client.post(f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=headers)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": answers},
        headers=headers,
    )

    assert response.status_code == 422


async def test_people_ops_cannot_submit_feedback(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, _, engagement = await _active(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": ANSWERS},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 403

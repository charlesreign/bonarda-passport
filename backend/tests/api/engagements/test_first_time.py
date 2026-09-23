from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.passport.enums import OnboardingState
from app.modules.passport.models import SkillClaim
from tests.support import (
    bearer,
    engagement_terms,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    make_worker,
)


def _url(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/engagements"


async def test_pm_engages_a_first_time_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["path"], body["status"]) == ("first_time", "pending_signature")
    assert body["confirmed_at"] is not None
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "engagements.engagement_created"
    assert event.payload == {
        "aggregate_id": body["id"],
        "worker_id": str(worker.id),
        "project_id": str(project.id),
        "path": "first_time",
    }
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id) == ("engagement.created", pm.id)


async def test_project_must_be_staffed_by_the_pm(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm])
    other = await make_project(session, name="Other")
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(other.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "project_not_found"


async def test_invited_worker_is_not_ready(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_worker(session, onboarding_state=OnboardingState.INVITED)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "worker_not_ready"


async def test_worker_who_removed_their_last_skill_is_not_ready(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    for claim in (await session.scalars(select(SkillClaim))).all():
        await session.delete(claim)
    await session.commit()

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.json()["code"] == "worker_not_ready"
    assert "skills" in response.json()["detail"]


async def test_worker_outside_the_projects_region_is_not_eligible(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    eu_project = await make_project(session, staff=[pm], data_region="EU", name="EU")
    worker, _ = await make_ready_worker(session, data_region="GH")

    response = await client.post(
        _url(worker.id), json=engagement_terms(eu_project.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "region_not_eligible"


async def test_worker_with_history_must_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    await make_engagement(session, worker_id=worker.id, project_id=(await make_project(session)).id)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.json()["code"] == "use_reactivation"


async def test_cancelled_history_does_not_count(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session)).id,
        status=EngagementStatus.CANCELLED,
    )

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"rate": "0"},
        {"currency": "ghs"},
        {"end_date": "2020-01-01"},
        {"work_mode": "moon"},
        {"worker_id": str(uuid4())},
        {"contract_terms": {"scope": ""}},
    ],
)
async def test_invalid_terms_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, overrides: dict[str, object]
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id),
        json=engagement_terms(project.id, **overrides),
        headers=bearer(settings, pm),
    )

    assert response.status_code == 422
    assert (await session.scalars(select(Engagement))).all() == []


async def test_people_ops_cannot_engage(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    project = await make_project(session)
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, ops)
    )

    assert response.status_code == 403

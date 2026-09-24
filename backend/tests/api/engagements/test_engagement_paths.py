from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.enums import EngagementStatus
from tests.support import (
    bearer,
    engagement_terms,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

KEY = {"Idempotency-Key": "path-rules-0001"}


async def test_an_unsigned_engagement_is_not_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.AWAITING_SIGNATURE,
    )

    first_time = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )

    assert first_time.status_code == 201
    assert first_time.json()["path"] == "first_time"


async def test_an_unsigned_engagement_cannot_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
    )

    response = await client.post(
        f"/api/v1/workers/{worker.id}/reactivations",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm) | KEY,
    )

    assert (response.status_code, response.json()["code"]) == (409, "no_prior_engagement")


async def test_a_returning_worker_with_a_profile_gap_can_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session, name="Old")).id
    )
    worker.languages = []
    await session.commit()

    response = await client.post(
        f"/api/v1/workers/{worker.id}/reactivations",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm) | KEY,
    )

    assert response.status_code == 201
    assert response.json()["path"] == "reactivation"


async def test_a_first_time_worker_with_a_profile_gap_is_still_not_ready(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    worker.languages = []
    await session.commit()

    response = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )

    assert (response.status_code, response.json()["code"]) == (409, "worker_not_ready")


async def test_prefill_agrees_with_reactivation_that_unsigned_is_not_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.AWAITING_SIGNATURE,
    )

    response = await client.get(
        f"/api/v1/workers/{worker.id}/reactivation-prefill",
        params={"project_id": str(project.id)},
        headers=bearer(settings, pm),
    )

    assert (response.status_code, response.json()["code"]) == (404, "no_prior_engagement")

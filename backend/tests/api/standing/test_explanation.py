from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import Project
from app.modules.identity.models import UserAccount
from app.modules.passport.models import Worker
from app.modules.standing.service import recalculate_all_standing
from tests.support import (
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_ready_worker,
    make_user,
    make_worker,
)


async def _tier_1_worker(
    session: AsyncSession,
) -> tuple[UserAccount, Worker, UserAccount, Project]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, account = await make_ready_worker(session)
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate_all_standing(session)
    await session.commit()
    return pm, worker, account, project


async def test_worker_sees_tier_factors_thresholds_and_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, worker, account, _ = await _tier_1_worker(session)

    response = await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))

    body = response.json()
    assert response.status_code == 200
    assert (body["worker_id"], body["tier"], body["policy_version"]) == (
        str(worker.id),
        "tier_1",
        1,
    )
    assert body["window_months"] == 24
    assert [t["tier"] for t in body["tiers"]] == ["tier_2", "tier_1"]
    assert body["factors"]["completed"] == 1
    assert body["factors"]["distinct_reviewers"] == 1
    assert body["factors"]["positive_ratio"] == 1.0
    assert body["evaluated_tier"] == "tier_1"
    (change,) = body["history"]
    assert (change["previous_tier"], change["new_tier"], change["policy_version"]) == (
        "unrated",
        "tier_1",
        1,
    )
    assert change["automated"] is True


async def test_detail_viewers_can_read_a_workers_standing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, worker, _, _ = await _tier_1_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    as_pm = await client.get(f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, pm))
    as_ops = await client.get(
        f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, ops)
    )

    assert (as_pm.status_code, as_ops.status_code) == (200, 200)


async def test_summary_level_pm_and_other_workers_get_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, worker, _, _ = await _tier_1_worker(session)
    stranger_pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[stranger_pm], data_region="GH", name="Nearby")
    _, other = await make_worker(session, email="other@example.com")

    summary = await client.get(
        f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, stranger_pm)
    )
    peer = await client.get(
        f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, other)
    )

    assert (summary.status_code, peer.status_code) == (404, 404)
    assert summary.json()["code"] == "worker_not_found"


async def test_staff_have_no_own_standing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get("/api/v1/workers/me/standing", headers=bearer(settings, ops))

    assert (response.status_code, response.json()["code"]) == (403, "not_a_worker")


async def test_a_new_worker_is_unrated_with_empty_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)

    body = (
        await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
    ).json()

    assert (body["tier"], body["history"], body["factors"]["completed"]) == ("unrated", [], 0)


async def test_the_evaluated_tier_shows_a_pending_change(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, account = await make_ready_worker(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    body = (
        await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
    ).json()

    assert (body["tier"], body["evaluated_tier"]) == ("unrated", "tier_1")

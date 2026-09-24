import copy
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import Project
from app.modules.identity.models import UserAccount
from app.modules.roster.enums import FirstShotOutcome
from app.modules.roster.models import FirstShotReview
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)


async def _small_pool_policy(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    """The seed excludes the top 10 candidates; tests use tiny pools."""
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 1
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/matching/versions",
        json={"rules": rules},
        headers=bearer(settings, author),
    )
    activated = await client.post(
        f"/api/v1/policies/matching/versions/{proposed.json()['version']}/activate",
        headers=bearer(settings, approver),
    )
    assert activated.status_code == 200


async def _setup(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> tuple[UserAccount, Project]:
    await _small_pool_policy(client, session, settings)
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    for i in range(4):
        await make_ready_worker(session, email=f"w{i}@example.com", full_name=f"Worker {i}")
    await refresh_roster(session)
    return pm, project


async def test_the_panel_logs_shown_impressions_once(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project = await _setup(client, session, settings)
    url = f"/api/v1/projects/{project.id}/first-shot"

    first = await client.get(url, headers=bearer(settings, pm))
    second = await client.get(url, headers=bearer(settings, pm))

    body = first.json()
    assert first.status_code == 200
    assert len(body["items"]) == 3  # 4 eligible minus the top candidate
    assert {i["outcome"] for i in body["items"]} == {"shown"}
    assert body["policy_version"] == 2
    assert [i["worker"]["worker_id"] for i in second.json()["items"]] == [
        i["worker"]["worker_id"] for i in body["items"]
    ]
    rows = (await session.scalars(select(FirstShotReview))).all()
    assert len(rows) == 3
    assert {r.pm_id for r in rows} == {pm.id}
    assert second.status_code == 200


async def test_serving_again_never_downgrades_an_outcome(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project = await _setup(client, session, settings)
    url = f"/api/v1/projects/{project.id}/first-shot"
    shown = (await client.get(url, headers=bearer(settings, pm))).json()["items"][0]
    row = (
        await session.scalars(
            select(FirstShotReview).where(FirstShotReview.worker_id == shown["worker"]["worker_id"])
        )
    ).one()
    row.outcome = FirstShotOutcome.SHORTLISTED
    await session.commit()

    again = (await client.get(url, headers=bearer(settings, pm))).json()["items"]

    outcomes = {i["worker"]["worker_id"]: i["outcome"] for i in again}
    assert outcomes[shown["worker"]["worker_id"]] == "shortlisted"


async def test_a_passed_worker_leaves_the_panel_for_a_new_eligible_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 0
    rules["first_shot"]["panel_size"] = 3
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/matching/versions",
        json={"rules": rules},
        headers=bearer(settings, author),
    )
    await client.post(
        f"/api/v1/policies/matching/versions/{proposed.json()['version']}/activate",
        headers=bearer(settings, approver),
    )
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    workers = []
    for i in range(4):
        worker, _ = await make_ready_worker(
            session, email=f"p{i}@example.com", full_name=f"Panel {i}"
        )
        workers.append(worker)
    await refresh_roster(session)
    url = f"/api/v1/projects/{project.id}/first-shot"

    first = (await client.get(url, headers=bearer(settings, pm))).json()["items"]
    assert len(first) == 3
    panel_ids = {i["worker"]["worker_id"] for i in first}
    waiting_id = next(str(w.id) for w in workers if str(w.id) not in panel_ids)
    passed_id = first[0]["worker"]["worker_id"]

    review = await client.post(
        f"/api/v1/projects/{project.id}/first-shot/{passed_id}/review",
        json={"outcome": "passed", "reason_code": "rate_mismatch"},
        headers=bearer(settings, pm),
    )
    assert review.status_code == 200

    second = (await client.get(url, headers=bearer(settings, pm))).json()["items"]
    second_ids = {i["worker"]["worker_id"] for i in second}
    assert len(second_ids) == 3
    assert passed_id not in second_ids
    assert waiting_id in second_ids


async def test_unstaffed_pm_cannot_open_the_panel(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, project = await _setup(client, session, settings)
    outsider = await make_user(session, role=UserRole.PM)

    response = await client.get(
        f"/api/v1/projects/{project.id}/first-shot", headers=bearer(settings, outsider)
    )

    assert (response.status_code, response.json()["code"]) == (404, "project_not_found")

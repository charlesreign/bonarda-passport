import copy
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.models import Project, ProjectStaff
from app.modules.identity.models import UserAccount
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)


async def _panel(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> tuple[UserAccount, Project, str]:
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 0
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
    project = await make_project(session, staff=[pm], data_region="EU")
    worker, account = await make_ready_worker(session, data_region="GH")
    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=bearer(settings, account),
    )
    await refresh_roster(session)
    items = (
        await client.get(f"/api/v1/projects/{project.id}/first-shot", headers=bearer(settings, pm))
    ).json()["items"]
    assert [i["worker"]["worker_id"] for i in items] == [str(worker.id)]
    return pm, project, str(worker.id)


def _review_url(project: Project, worker_id: str) -> str:
    return f"/api/v1/projects/{project.id}/first-shot/{worker_id}/review"


async def _view(
    client: AsyncClient, settings: Settings, pm: UserAccount, worker_id: str
) -> str | None:
    response = await client.get(f"/api/v1/workers/{worker_id}", headers=bearer(settings, pm))
    return response.json()["view"] if response.status_code == 200 else None


async def test_shortlisting_grants_detail_and_is_audited(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    before = await _view(client, settings, pm, worker_id)

    response = await client.post(
        _review_url(project, worker_id),
        json={"outcome": "shortlisted"},
        headers=bearer(settings, pm),
    )

    assert response.status_code == 200
    assert (response.json()["outcome"], response.json()["reason_code"]) == ("shortlisted", None)
    assert (before, await _view(client, settings, pm, worker_id)) == ("summary", "detail")
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "first_shot.reviewed"))
    ).one()
    assert (audit.actor_id, str(audit.target_id)) == (pm.id, worker_id)
    assert audit.before == {"outcome": "shown"}
    assert audit.after == {
        "project_id": str(project.id),
        "outcome": "shortlisted",
        "reason_code": None,
    }


async def test_passing_needs_a_reason_and_never_grants_detail(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    url = _review_url(project, worker_id)
    headers = bearer(settings, pm)

    no_reason = await client.post(url, json={"outcome": "passed"}, headers=headers)
    stray_reason = await client.post(
        url, json={"outcome": "contacted", "reason_code": "other"}, headers=headers
    )
    passed = await client.post(
        url, json={"outcome": "passed", "reason_code": "rate_mismatch"}, headers=headers
    )

    assert (no_reason.status_code, stray_reason.status_code, passed.status_code) == (422, 422, 200)
    assert await _view(client, settings, pm, worker_id) == "summary"


async def test_detail_ends_when_staffing_ends(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    contacted = await client.post(
        _review_url(project, worker_id), json={"outcome": "contacted"}, headers=bearer(settings, pm)
    )
    assert contacted.status_code == 200
    assert await _view(client, settings, pm, worker_id) == "detail"

    await session.execute(update(ProjectStaff).values(active_to=utcnow()))
    await session.commit()

    assert await _view(client, settings, pm, worker_id) is None


@pytest.mark.parametrize("who", ["not_shown", "outsider"])
async def test_reviews_need_a_shown_worker_and_a_staffed_pm(
    client: AsyncClient, session: AsyncSession, settings: Settings, who: str
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    if who == "not_shown":
        other, _ = await make_ready_worker(session, email="other@example.com", data_region="EU")
        response = await client.post(
            _review_url(project, str(other.id)),
            json={"outcome": "shortlisted"},
            headers=bearer(settings, pm),
        )
        expected = (404, "not_in_first_shot")
    else:
        outsider = await make_user(session, role=UserRole.PM)
        await make_project(session, staff=[outsider], data_region="EU", name="Theirs")
        response = await client.post(
            _review_url(project, worker_id),
            json={"outcome": "shortlisted"},
            headers=bearer(settings, outsider),
        )
        expected = (404, "project_not_found")

    assert (response.status_code, response.json()["code"]) == expected


async def test_review_rejects_a_worker_no_longer_eligible_for_the_region(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    account = (
        await session.scalars(select(UserAccount).where(UserAccount.worker_id == UUID(worker_id)))
    ).one()
    # A detail outcome first, so the worker stays visible to the PM (via the
    # first-shot visibility source) after they withdraw consent below.
    contacted = await client.post(
        _review_url(project, worker_id), json={"outcome": "contacted"}, headers=bearer(settings, pm)
    )
    assert contacted.status_code == 200

    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": False},
        headers=bearer(settings, account),
    )
    await refresh_roster(session)

    shortlisted = await client.post(
        _review_url(project, worker_id),
        json={"outcome": "shortlisted"},
        headers=bearer(settings, pm),
    )
    passed = await client.post(
        _review_url(project, worker_id),
        json={"outcome": "passed", "reason_code": "rate_mismatch"},
        headers=bearer(settings, pm),
    )

    assert (shortlisted.status_code, shortlisted.json()["code"]) == (409, "worker_not_eligible")
    assert passed.status_code == 200

from collections.abc import Awaitable, Callable
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.passport.enums import (
    AvailabilityStatus,
    OnboardingState,
    VerificationStatus,
    WorkerStatus,
)
from app.modules.passport.models import Skill, SkillClaim
from tests.support import (
    bearer,
    make_project,
    make_ready_worker,
    make_user,
    make_worker,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


def _url(project_id: object) -> str:
    return f"/api/v1/projects/{project_id}/candidates"


async def _skill(session: AsyncSession) -> Skill:
    return (await session.scalars(select(Skill).where(Skill.slug == "data-analysis"))).one()


async def _verify(session: AsyncSession, worker_id: object, skill: Skill) -> None:
    claim = (
        await session.scalars(
            select(SkillClaim).where(
                SkillClaim.worker_id == worker_id, SkillClaim.skill_id == skill.id
            )
        )
    ).one()
    claim.verification_status = VerificationStatus.BONARDA_VERIFIED
    await session.commit()


async def test_candidates_are_region_eligible_scored_and_summary_only(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    kofi, _ = await make_ready_worker(session, email="kofi@example.com", full_name="Kofi")
    skill = await _skill(session)
    project = await make_project(session, staff=[pm], required_skill_ids=[skill.id])
    ama, _ = await make_ready_worker(session, email="ama@example.com", full_name="Ama")
    await _verify(session, ama.id, skill)
    lea, _ = await make_ready_worker(
        session, email="lea@example.com", full_name="Léa", data_region="EU"
    )
    await make_worker(session, email="new@example.com", onboarding_state=OnboardingState.INVITED)
    await make_worker(session, email="gone@example.com", status=WorkerStatus.ANONYMIZED)
    await refresh_roster(session)

    response = await client.get(_url(project.id), headers=bearer(settings, pm))

    body = response.json()
    assert response.status_code == 200
    assert [c["worker"]["display_name"] for c in body["items"]] == ["Ama", "Kofi"]
    top = body["items"][0]
    assert top["score"] == 0.65
    assert top["score_breakdown"]["verified_skills"]["points"] == 0.5
    assert top["score_breakdown"]["policy_version"] == 1
    assert set(top["worker"]) == {
        "worker_id",
        "display_name",
        "standing_tier",
        "verified_skill_ids",
        "self_reported_skill_ids",
        "availability_status",
        "available_from",
        "base_location",
        "engagements_total",
    }
    assert body["next_cursor"] is None
    assert str(lea.id) not in {c["worker"]["worker_id"] for c in body["items"]}


async def test_withdrawing_cross_region_consent_removes_a_candidate(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="EU")
    worker, account = await make_ready_worker(session, data_region="GH")
    worker_headers = bearer(settings, account)
    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=worker_headers,
    )
    await drain()
    with_consent = await client.get(_url(project.id), headers=bearer(settings, pm))

    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": False},
        headers=worker_headers,
    )
    await drain()
    without_consent = await client.get(_url(project.id), headers=bearer(settings, pm))

    assert [c["worker"]["worker_id"] for c in with_consent.json()["items"]] == [str(worker.id)]
    assert without_consent.json()["items"] == []


async def test_filters_narrow_the_pool(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    await make_ready_worker(session, email="kofi@example.com", full_name="Kofi 100%")
    ama, _ = await make_ready_worker(session, email="ama@example.com", full_name="Ama")
    ama.base_location = "Kumasi"
    ama.availability_status = AvailabilityStatus.UNAVAILABLE
    await session.commit()
    python = Skill(slug="python", name_i18n={"en": "Python"})
    session.add(python)
    await session.flush()
    session.add(SkillClaim(worker_id=ama.id, skill_id=python.id))
    await session.commit()
    await refresh_roster(session)
    headers = bearer(settings, pm)

    async def names(**params: object) -> list[str]:
        response = await client.get(_url(project.id), params=params, headers=headers)
        return [c["worker"]["display_name"] for c in response.json()["items"]]

    assert await names(skill_ids=str(python.id)) == ["Ama"]
    assert await names(location="kumasi") == ["Ama"]
    assert await names(availability="unavailable") == ["Ama"]
    assert await names(q="100%") == ["Kofi 100%"]
    assert await names(q="%") == ["Kofi 100%"]


async def test_the_cursor_walks_every_candidate_once(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], starts_on=utcnow().date() + timedelta(days=7))
    for i in range(5):
        await make_ready_worker(session, email=f"w{i}@example.com", full_name=f"Worker {i}")
    await refresh_roster(session)
    headers = bearer(settings, pm)

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params: dict[str, object] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get(_url(project.id), params=params, headers=headers)).json()
        seen += [c["worker"]["worker_id"] for c in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_bad_cursor_unstaffed_pm_and_other_roles(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    outsider = await make_user(session, role=UserRole.PM)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    project = await make_project(session, staff=[pm])

    bad = await client.get(
        _url(project.id), params={"cursor": "not-a-cursor"}, headers=bearer(settings, pm)
    )
    unstaffed = await client.get(_url(project.id), headers=bearer(settings, outsider))
    people_ops = await client.get(_url(project.id), headers=bearer(settings, ops))

    assert (bad.status_code, bad.json()["code"]) == (400, "invalid_cursor")
    assert (unstaffed.status_code, unstaffed.json()["code"]) == (404, "project_not_found")
    assert people_ops.status_code == 403

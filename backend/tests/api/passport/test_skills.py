from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.passport.repository import SkillClaimRepository, SkillRepository
from tests.support import bearer, make_user, make_worker


async def _skill(session: AsyncSession, slug: str, en: str, fr: str | None = None) -> Skill:
    names = {"en": en} | ({"fr": fr} if fr else {})
    skill = Skill(slug=slug, name_i18n=names)
    session.add(skill)
    await session.commit()
    return skill


async def test_people_ops_adds_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "data-analysis", "name_i18n": {"en": "Data analysis", "fr": "Analyse"}},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "data-analysis"
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id) == ("skill.created", ops.id)


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "Data Analysis", "name_i18n": {"en": "Data analysis"}},
        {"slug": "data-analysis", "name_i18n": {"fr": "Analyse"}},
        {"slug": "data-analysis", "name_i18n": {"en": ""}},
    ],
)
async def test_invalid_skill_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, body: dict[str, object]
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post("/api/v1/skills", json=body, headers=bearer(settings, ops))

    assert response.status_code == 422


async def test_duplicate_slug_is_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _skill(session, "data-analysis", "Data analysis")

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "data-analysis", "name_i18n": {"en": "Data analysis"}},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "skill_slug_taken"


async def test_concurrent_duplicate_slug_is_a_conflict_not_a_crash(
    client: AsyncClient, session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _skill(session, "data-analysis", "Data analysis")

    async def not_found(self: SkillRepository, slug: str) -> None:
        return None  # simulate the race: the pre-check misses the other insert

    monkeypatch.setattr(SkillRepository, "get_by_slug", not_found)

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "data-analysis", "name_i18n": {"en": "Data analysis"}},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "skill_slug_taken"


async def test_concurrent_duplicate_claim_is_a_conflict_not_a_crash(
    client: AsyncClient, session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    session.add(SkillClaim(worker_id=worker.id, skill_id=skill.id))
    await session.commit()

    async def not_found(self: SkillClaimRepository, worker_id: object, skill_id: object) -> None:
        return None

    monkeypatch.setattr(SkillClaimRepository, "get", not_found)

    response = await client.post(
        "/api/v1/workers/me/skills",
        json={"skill_id": str(skill.id)},
        headers=bearer(settings, account),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "skill_already_claimed"


async def test_pm_cannot_add_skills(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "x", "name_i18n": {"en": "X"}},
        headers=bearer(settings, pm),
    )

    assert response.status_code == 403


async def test_search_matches_slug_and_localized_names(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)
    await _skill(session, "data-analysis", "Data analysis", "Analyse de données")
    await _skill(session, "project-management", "Project management", "Gestion de projet")
    headers = bearer(settings, user)

    by_slug = await client.get("/api/v1/skills", params={"q": "data"}, headers=headers)
    by_french = await client.get("/api/v1/skills", params={"q": "gestion"}, headers=headers)
    everything = await client.get("/api/v1/skills", params={"limit": 1}, headers=headers)

    assert [s["slug"] for s in by_slug.json()] == ["data-analysis"]
    assert [s["slug"] for s in by_french.json()] == ["project-management"]
    assert len(everything.json()) == 1


@pytest.mark.parametrize("term", ["%", "_", "data%"])
async def test_search_treats_wildcards_literally(
    client: AsyncClient, session: AsyncSession, settings: Settings, term: str
) -> None:
    user = await make_user(session, role=UserRole.PM)
    await _skill(session, "data-analysis", "Data analysis")

    response = await client.get(
        "/api/v1/skills", params={"q": term}, headers=bearer(settings, user)
    )

    assert response.json() == []


async def test_worker_claims_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")

    response = await client.post(
        "/api/v1/workers/me/skills",
        json={"skill_id": str(skill.id)},
        headers=bearer(settings, account),
    )

    assert response.status_code == 201
    assert response.json() == {
        "skill_id": str(skill.id),
        "slug": "data-analysis",
        "verification_status": "self_reported",
    }
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "passport.worker_updated"
    assert event.payload == {"aggregate_id": str(worker.id), "fields": ["skills"]}


async def test_claiming_twice_or_an_unknown_skill_fails(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    headers = bearer(settings, account)
    await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=headers
    )

    again = await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=headers
    )
    unknown = await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(uuid4())}, headers=headers
    )

    assert again.json()["code"] == "skill_already_claimed"
    assert unknown.json()["code"] == "skill_not_found"


async def test_staff_cannot_claim_skills(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    skill = await _skill(session, "data-analysis", "Data analysis")

    response = await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=bearer(settings, pm)
    )

    assert response.status_code == 403


async def test_worker_removes_a_self_reported_claim(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    session.add(SkillClaim(worker_id=worker.id, skill_id=skill.id))
    await session.commit()

    response = await client.delete(
        f"/api/v1/workers/me/skills/{skill.id}", headers=bearer(settings, account)
    )

    assert response.status_code == 204
    assert (await session.scalars(select(SkillClaim))).all() == []


async def test_verified_claims_cannot_be_removed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    session.add(
        SkillClaim(
            worker_id=worker.id,
            skill_id=skill.id,
            verification_status=VerificationStatus.BONARDA_VERIFIED,
        )
    )
    await session.commit()
    headers = bearer(settings, account)

    locked = await client.delete(f"/api/v1/workers/me/skills/{skill.id}", headers=headers)
    missing = await client.delete(f"/api/v1/workers/me/skills/{uuid4()}", headers=headers)

    assert locked.json()["code"] == "skill_verified_locked"
    assert missing.json()["code"] == "claim_not_found"

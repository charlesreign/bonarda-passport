from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.identity.service import Visibility, VisibilityPolicy
from app.modules.passport.enums import OnboardingState
from app.modules.passport.models import Skill, SkillClaim
from tests.support import bearer, make_user, make_worker


async def _add_skill_claim(session: AsyncSession, worker_id: UUID) -> Skill:
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.flush()
    session.add(SkillClaim(worker_id=worker_id, skill_id=skill.id))
    await session.commit()
    return skill


async def test_worker_reads_their_own_passport(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session, email="kofi@example.com", locale="fr")
    await _add_skill_claim(session, worker.id)

    response = await client.get("/api/v1/workers/me", headers=bearer(settings, account))

    body = response.json()
    assert response.status_code == 200
    assert (body["view"], body["id"], body["email"], body["locale"]) == (
        "self",
        str(worker.id),
        "kofi@example.com",
        "fr",
    )
    assert [s["slug"] for s in body["skills"]] == ["data-analysis"]


async def test_people_ops_sees_detail_without_contact_details(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(f"/api/v1/workers/{worker.id}", headers=bearer(settings, ops))

    body = response.json()
    assert body["view"] == "detail"
    assert "languages" in body
    assert "email" not in body


async def test_summary_viewer_gets_only_the_search_card(
    app: FastAPI, client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    pm = await make_user(session, role=UserRole.PM)

    async def summary(s: AsyncSession, a: Actor, w: UUID) -> Visibility:
        return Visibility.SUMMARY

    app.state.visibility_policy = VisibilityPolicy([summary])

    response = await client.get(f"/api/v1/workers/{worker.id}", headers=bearer(settings, pm))

    body = response.json()
    assert body["view"] == "summary"
    assert "languages" not in body
    assert "onboarding_state" not in body


@pytest.mark.parametrize("role", [UserRole.PM, UserRole.FINANCE])
async def test_staff_without_visibility_get_404(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    worker, _ = await make_worker(session)
    user = await make_user(session, role=role)

    response = await client.get(f"/api/v1/workers/{worker.id}", headers=bearer(settings, user))

    assert response.status_code == 404
    assert response.json()["code"] == "worker_not_found"


async def test_unknown_worker_is_404_even_for_people_ops(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(f"/api/v1/workers/{uuid4()}", headers=bearer(settings, ops))

    assert response.json()["code"] == "worker_not_found"


async def test_worker_updates_their_profile(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)

    response = await client.patch(
        "/api/v1/workers/me",
        json={
            "base_location": "Accra",
            "languages": ["en", "fr", "en"],
            "availability_status": "available_from",
            "available_from": "2026-11-01",
        },
        headers=bearer(settings, account),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["languages"] == ["en", "fr"]  # de-duplicated, order kept
    assert (body["availability_status"], body["available_from"]) == ("available_from", "2026-11-01")
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "passport.worker_updated"
    assert event.payload["fields"] == [
        "availability_status",
        "available_from",
        "base_location",
        "languages",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"languages": ["EN"]},
        {"full_name": None},
        {"languages": None},
        {"availability_status": None},
        {"worker_id": str(uuid4())},
    ],
)
async def test_invalid_profile_updates_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, body: dict[str, object]
) -> None:
    _, account = await make_worker(session)

    response = await client.patch(
        "/api/v1/workers/me", json=body, headers=bearer(settings, account)
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"availability_status": "available_from"}, "availability_date_required"),
        ({"available_from": "2026-11-01"}, "availability_status_mismatch"),
        (
            {"availability_status": "available", "available_from": "2026-11-01"},
            "availability_status_mismatch",
        ),
    ],
)
async def test_inconsistent_availability_is_rejected_with_a_code(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    body: dict[str, object],
    code: str,
) -> None:
    _, account = await make_worker(session)

    response = await client.patch(
        "/api/v1/workers/me", json=body, headers=bearer(settings, account)
    )

    assert response.status_code == 422
    assert response.json()["code"] == code


async def test_worker_already_available_from_can_move_the_date(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "available_from", "available_from": "2026-11-01"},
        headers=headers,
    )

    response = await client.patch(
        "/api/v1/workers/me", json={"available_from": "2026-12-01"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["available_from"] == "2026-12-01"


async def test_base_location_can_be_cleared(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.patch("/api/v1/workers/me", json={"base_location": "Accra"}, headers=headers)

    response = await client.patch(
        "/api/v1/workers/me", json={"base_location": None}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["base_location"] is None


async def test_becoming_available_clears_the_available_from_date(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "available_from", "available_from": "2026-11-01"},
        headers=headers,
    )

    response = await client.patch(
        "/api/v1/workers/me", json={"availability_status": "available"}, headers=headers
    )

    assert response.json()["available_from"] is None


async def test_onboarding_requires_location_languages_and_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session, onboarding_state=OnboardingState.INVITED)
    headers = bearer(settings, account)

    early = await client.post("/api/v1/workers/me/onboarding/complete", headers=headers)
    await client.patch(
        "/api/v1/workers/me",
        json={"base_location": "Accra", "languages": ["en"]},
        headers=headers,
    )
    await _add_skill_claim(session, worker.id)
    done = await client.post("/api/v1/workers/me/onboarding/complete", headers=headers)
    again = await client.post("/api/v1/workers/me/onboarding/complete", headers=headers)

    assert early.status_code == 409
    assert early.json()["code"] == "onboarding_incomplete"
    assert "base_location" in early.json()["detail"]
    assert done.json()["onboarding_state"] == "profile_complete"
    assert again.status_code == 200
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions.count("worker.onboarding_completed") == 1

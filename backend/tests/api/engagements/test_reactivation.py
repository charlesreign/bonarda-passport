from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.enums import EngagementStatus, WorkMode
from app.modules.engagements.models import Engagement, Project
from app.modules.engagements.repository import EngagementRepository
from app.modules.passport.models import Worker
from tests.support import (
    bearer,
    engagement_terms,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

KEY = {"Idempotency-Key": "reactivate-kofi-0001"}


def _miss_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates two requests racing past the idempotency-key lookup: the
    first call (the one before `create()`) reports no existing row, as if
    the concurrent winner's insert were not yet visible; every later call
    (including the post-conflict fallback in `reactivate()`) behaves
    normally."""
    real = EngagementRepository.get_by_idempotency_key
    calls = {"n": 0}

    async def flaky(self: EngagementRepository, key: str) -> Engagement | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real(self, key)

    monkeypatch.setattr(EngagementRepository, "get_by_idempotency_key", flaky)


def _prefill(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/reactivation-prefill"


def _reactivate(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/reactivations"


async def _kofi_with_history(session: AsyncSession) -> tuple[Worker, Engagement, Project]:
    """Kofi worked on another PM's project; Ama now staffs a new GH project."""
    worker, _ = await make_ready_worker(session)
    old_project = await make_project(session, name="Old")
    older = await make_engagement(
        session, worker_id=worker.id, project_id=old_project.id, start_date=date(2025, 1, 6)
    )
    latest = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=old_project.id,
        start_date=date(2025, 9, 1),
        rate=Decimal("520.00"),
        work_mode=WorkMode.HYBRID,
        scope="Maintain the pipeline",
    )
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=old_project.id,
        start_date=date(2026, 1, 1),
        status=EngagementStatus.CANCELLED,
    )
    assert older.id != latest.id
    return worker, latest, old_project


async def test_prefill_returns_the_latest_non_cancelled_terms(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, latest, _ = await _kofi_with_history(session)

    response = await client.get(
        _prefill(worker.id), params={"project_id": str(project.id)}, headers=bearer(settings, ama)
    )

    body = response.json()
    assert response.status_code == 200
    assert body["prefilled_from_engagement_id"] == str(latest.id)
    assert (body["rate"], body["work_mode"]) == ("520.00", "hybrid")
    assert body["contract_terms"]["scope"] == "Maintain the pipeline"
    assert "feedback" not in body


async def test_prefill_without_history_is_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])
    worker, _ = await make_ready_worker(session)

    response = await client.get(
        _prefill(worker.id), params={"project_id": str(project.id)}, headers=bearer(settings, ama)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "no_prior_engagement"


async def test_reactivation_creates_one_engagement_even_when_replayed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, latest, _ = await _kofi_with_history(session)
    body = engagement_terms(project.id, prefilled_from_engagement_id=str(latest.id))
    headers = bearer(settings, ama) | KEY

    first = await client.post(_reactivate(worker.id), json=body, headers=headers)
    second = await client.post(_reactivate(worker.id), json=body, headers=headers)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["path"] == "reactivation"
    assert first.json()["prefilled_from_engagement_id"] == str(latest.id)
    new = (
        await session.scalars(select(Engagement).where(Engagement.project_id == project.id))
    ).all()
    assert len(new) == 1


async def test_key_reused_for_another_worker_is_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    kofi, _, old = await _kofi_with_history(session)
    grace, _ = await make_ready_worker(session, email="grace@example.com")
    await make_engagement(session, worker_id=grace.id, project_id=old.id)
    headers = bearer(settings, ama) | KEY
    await client.post(_reactivate(kofi.id), json=engagement_terms(project.id), headers=headers)

    response = await client.post(
        _reactivate(grace.id), json=engagement_terms(project.id), headers=headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_key_reused"


async def test_idempotency_key_is_required_and_well_formed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, _, _ = await _kofi_with_history(session)
    url = _reactivate(worker.id)
    body = engagement_terms(project.id)

    missing = await client.post(url, json=body, headers=bearer(settings, ama))
    malformed = await client.post(
        url, json=body, headers=bearer(settings, ama) | {"Idempotency-Key": "bad key!"}
    )

    assert missing.json()["code"] == "idempotency_key_required"
    assert malformed.json()["code"] == "idempotency_key_required"


async def test_prefill_source_must_belong_to_the_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    kofi, _, old = await _kofi_with_history(session)
    grace, _ = await make_ready_worker(session, email="grace@example.com")
    graces = await make_engagement(session, worker_id=grace.id, project_id=old.id)

    response = await client.post(
        _reactivate(kofi.id),
        json=engagement_terms(project.id, prefilled_from_engagement_id=str(graces.id)),
        headers=bearer(settings, ama) | KEY,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_prefill_source"


async def test_open_engagement_on_the_same_project_is_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, _, _ = await _kofi_with_history(session)
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.ACTIVE
    )

    response = await client.post(
        _reactivate(worker.id),
        json=engagement_terms(project.id),
        headers=bearer(settings, ama) | KEY,
    )

    assert response.json()["code"] == "engagement_already_open"


async def test_first_timer_cannot_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _reactivate(worker.id),
        json=engagement_terms(project.id),
        headers=bearer(settings, ama) | KEY,
    )

    assert response.json()["code"] == "no_prior_engagement"


async def test_reactivation_replays_across_a_race_for_the_same_pm(
    client: AsyncClient, session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two requests race past the idempotency-key lookup (double-click, or a
    client retry that overlaps the first attempt). The loser must still see
    the winner's engagement with 200, not a 409."""
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, latest, _ = await _kofi_with_history(session)
    body = engagement_terms(project.id, prefilled_from_engagement_id=str(latest.id))
    headers = bearer(settings, ama) | KEY

    first = await client.post(_reactivate(worker.id), json=body, headers=headers)
    assert first.status_code == 201

    _miss_once(monkeypatch)
    second = await client.post(_reactivate(worker.id), json=body, headers=headers)

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    new = (
        await session.scalars(select(Engagement).where(Engagement.project_id == project.id))
    ).all()
    assert len(new) == 1


async def test_reactivation_still_conflicts_when_a_different_pm_races_the_key(
    client: AsyncClient, session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race-replay fallback must not hand a different PM's or a
    different worker's engagement back as a 'replay'."""
    ama = await make_user(session, role=UserRole.PM)
    mercy = await make_user(session, role=UserRole.PM, email="mercy.pm@example.com")
    project = await make_project(session, staff=[ama, mercy], name="New")
    kofi, _, old = await _kofi_with_history(session)
    grace, _ = await make_ready_worker(session, email="grace@example.com")
    await make_engagement(session, worker_id=grace.id, project_id=old.id)

    first = await client.post(
        _reactivate(kofi.id), json=engagement_terms(project.id), headers=bearer(settings, ama) | KEY
    )
    assert first.status_code == 201

    _miss_once(monkeypatch)
    second = await client.post(
        _reactivate(grace.id),
        json=engagement_terms(project.id),
        headers=bearer(settings, mercy) | KEY,
    )

    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_key_reused"

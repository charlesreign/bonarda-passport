import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim, Worker
from app.modules.passport.schemas import RosterWorker
from app.modules.roster import refresh as refresh_module
from app.modules.roster.models import RosterProfile
from app.modules.roster.refresh import refresh_worker
from tests.support import (
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


async def _profile(session: AsyncSession, worker: Worker) -> RosterProfile:
    profile = await session.get(RosterProfile, worker.id)
    assert profile is not None
    await session.refresh(profile)
    return profile


async def test_invited_workers_appear_after_the_relay_runs(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    response = await client.post(
        "/api/v1/workers/invitations",
        json={
            "email": "kofi@example.com",
            "full_name": "Kofi Mensah",
            "worker_type": "freelancer",
            "data_region": "GH",
        },
        headers=bearer(settings, pm),
    )

    await drain()

    profile = await session.get(RosterProfile, response.json()["worker_id"])
    assert profile is not None
    assert (profile.display_name, profile.status, profile.onboarding_state) == (
        "Kofi Mensah",
        "dormant",
        "invited",
    )


async def test_the_row_projects_skills_and_signed_engagement_counts(
    session: AsyncSession,
) -> None:
    worker, _ = await make_ready_worker(session)
    project = await make_project(session)
    today = utcnow().date()
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, start_date=today - timedelta(days=30)
    )
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, start_date=today - timedelta(days=400)
    )
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
        start_date=today,
    )
    python = Skill(slug="python", name_i18n={"en": "Python"})
    session.add(python)
    await session.flush()
    session.add(
        SkillClaim(
            worker_id=worker.id,
            skill_id=python.id,
            verification_status=VerificationStatus.BONARDA_VERIFIED,
        )
    )
    await session.commit()

    await refresh_roster(session)

    profile = await _profile(session, worker)
    assert set(profile.skill_ids) == {s.id for s in (await session.scalars(select(Skill))).all()}
    assert profile.verified_skill_ids == [python.id]
    assert (profile.engagements_total, profile.engagements_last_12m) == (2, 1)
    assert profile.last_engaged_on == today - timedelta(days=30)
    assert (profile.base_location, profile.availability_status) == ("Accra", "available")


async def test_profile_edits_reach_the_roster_through_events(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    await refresh_roster(session)

    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "unavailable"},
        headers=bearer(settings, account),
    )
    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=bearer(settings, account),
    )
    await drain()

    profile = await _profile(session, worker)
    assert (profile.availability_status, profile.cross_region_ok) == ("unavailable", True)


async def test_the_nightly_rebuild_repairs_drift(session: AsyncSession) -> None:
    worker, _ = await make_ready_worker(session)
    await refresh_roster(session)
    await session.execute(
        update(RosterProfile)
        .where(RosterProfile.worker_id == worker.id)
        .values(display_name="Stale", standing_tier="tier_2")
    )
    await session.commit()

    await refresh_roster(session)

    profile = await _profile(session, worker)
    assert (profile.display_name, profile.standing_tier) == ("Kofi Mensah", "unrated")


async def test_concurrent_refreshes_keep_the_latest_committed_state(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow refresh that read an old snapshot must not commit it after a newer
    refresh. Without the per-worker advisory lock, the second refresh finishes
    first and the slow one overwrites it with the stale name."""
    worker, _ = await make_ready_worker(session)
    real_snapshot = refresh_module.roster_snapshot
    first_has_read = asyncio.Event()
    second_done = asyncio.Event()
    calls = 0

    async def slow_snapshot(s: AsyncSession, worker_id: UUID) -> RosterWorker | None:
        nonlocal calls
        calls += 1
        snapshot = await real_snapshot(s, worker_id)
        if calls == 1:
            first_has_read.set()
            try:
                # With the lock the second refresh is blocked, so this times out.
                await asyncio.wait_for(second_done.wait(), timeout=1)
            except TimeoutError:
                pass
        return snapshot

    monkeypatch.setattr(refresh_module, "roster_snapshot", slow_snapshot)

    async def first() -> None:
        async with sessionmaker() as s, s.begin():
            await refresh_worker(s, worker.id)

    async def second() -> None:
        await first_has_read.wait()
        async with sessionmaker() as s, s.begin():
            await s.execute(
                update(Worker).where(Worker.id == worker.id).values(full_name="Kofi A. Mensah")
            )
        async with sessionmaker() as s, s.begin():
            await refresh_worker(s, worker.id)
        second_done.set()

    await asyncio.wait_for(asyncio.gather(first(), second()), timeout=15)

    assert (await _profile(session, worker)).display_name == "Kofi A. Mensah"

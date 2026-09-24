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
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.schemas import ContractSigned, EngagementCompleted
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim, Worker
from app.modules.passport.schemas import RosterWorker
from app.modules.roster import refresh as refresh_module
from app.modules.roster.models import RosterProfile
from app.modules.roster.refresh import rebuild_all, refresh_worker
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
    assert response.status_code == 201

    await drain()

    profile = await session.get(RosterProfile, UUID(response.json()["worker_id"]))
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
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Upcoming")).id,
        status=EngagementStatus.SIGNED,
        start_date=today + timedelta(days=10),
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
    # 3 history engagements (two past, one SIGNED with a future start date);
    # only the past ones count toward last_12m, and the future one must not
    # become last_engaged_on.
    assert (profile.engagements_total, profile.engagements_last_12m) == (3, 1)
    assert profile.last_engaged_on == today - timedelta(days=30)
    assert (profile.base_location, profile.availability_status) == ("Accra", "available")


async def test_profile_edits_reach_the_roster_through_events(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    await refresh_roster(session)

    patch_response = await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "unavailable"},
        headers=bearer(settings, account),
    )
    assert patch_response.status_code == 200
    put_response = await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=bearer(settings, account),
    )
    assert put_response.status_code == 200
    await drain()

    profile = await _profile(session, worker)
    assert (profile.availability_status, profile.cross_region_ok) == ("unavailable", True)


async def test_consent_changes_flow_through_to_cross_region_ok(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    """Isolates ConsentChanged from the other events in the test above:
    granting then withdrawing must each round-trip through the roster."""
    worker, account = await make_ready_worker(session)
    await refresh_roster(session)
    headers = bearer(settings, account)
    url = "/api/v1/workers/me/consents/cross_region_matching"

    grant_response = await client.put(url, json={"granted": True}, headers=headers)
    assert grant_response.status_code == 200
    await drain()
    assert (await _profile(session, worker)).cross_region_ok is True

    withdraw_response = await client.put(url, json={"granted": False}, headers=headers)
    assert withdraw_response.status_code == 200
    await drain()
    assert (await _profile(session, worker)).cross_region_ok is False


async def test_engagement_events_refresh_the_roster(session: AsyncSession, drain: Drain) -> None:
    """Exercises both engagement handler paths: EngagementCompleted carries
    worker_id directly, ContractSigned carries only the engagement id and is
    resolved to a worker through engagement_worker_id."""
    worker, _ = await make_ready_worker(session)
    project = await make_project(session)
    await refresh_roster(session)
    assert (await _profile(session, worker)).engagements_total == 0

    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.SIGNED
    )

    await emit_event(
        session,
        EngagementCompleted(aggregate_id=engagement.id, worker_id=worker.id, project_id=project.id),
    )
    await session.commit()
    await drain()
    assert (await _profile(session, worker)).engagements_total == 1

    await emit_event(session, ContractSigned(aggregate_id=engagement.id))
    await session.commit()
    await drain()
    assert (await _profile(session, worker)).engagements_total == 1


async def test_rebuild_all_batches_refresh_every_worker(session: AsyncSession) -> None:
    workers = []
    for i in range(5):
        worker, _ = await make_ready_worker(session, email=f"batch{i}@example.com")
        workers.append(worker)

    count = await rebuild_all(session, batch_size=2)

    assert count == 5
    for worker in workers:
        assert await session.get(RosterProfile, worker.id) is not None


async def test_rebuild_all_commits_between_batches(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rebuild_all(batch_size=2) commits after every batch, so a worker
    refreshed in an earlier batch is visible to a concurrent reader (and its
    advisory lock released) well before the whole rebuild finishes -- not
    only relying on a final commit."""
    workers = []
    for i in range(5):
        worker, _ = await make_ready_worker(session, email=f"paced{i}@example.com")
        workers.append(worker)
    await session.commit()
    workers.sort(key=lambda w: w.id)

    real_refresh_worker = refresh_module.refresh_worker
    calls = 0
    paused_before_third = asyncio.Event()
    resume = asyncio.Event()

    async def paced_refresh_worker(s: AsyncSession, worker_id: UUID) -> bool:
        nonlocal calls
        calls += 1
        if calls == 3:
            # The first batch (2 workers) has already been committed by
            # rebuild_all's loop by the time its third call starts.
            paused_before_third.set()
            await resume.wait()
        return await real_refresh_worker(s, worker_id)

    monkeypatch.setattr(refresh_module, "refresh_worker", paced_refresh_worker)

    async def run_rebuild() -> None:
        async with sessionmaker() as s:
            await refresh_module.rebuild_all(s, batch_size=2)

    task = asyncio.create_task(run_rebuild())
    await asyncio.wait_for(paused_before_third.wait(), timeout=5)

    async with sessionmaker() as reader:
        assert await reader.get(RosterProfile, workers[0].id) is not None
        assert await reader.get(RosterProfile, workers[1].id) is not None
        assert await reader.get(RosterProfile, workers[2].id) is None

    resume.set()
    await asyncio.wait_for(task, timeout=5)

    async with sessionmaker() as reader:
        for worker in workers:
            assert await reader.get(RosterProfile, worker.id) is not None


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

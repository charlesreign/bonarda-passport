import asyncio
import copy
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import StandingTier, VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.standing import evidence, recalculation
from app.modules.standing.evidence import record_skill_evidence
from app.modules.standing.models import SkillEvidence, StandingChange
from app.modules.standing.recalculation import recalculate_all
from app.modules.standing.service import recalculate_all_standing
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


def _tiering(**changes: Any) -> dict[str, Any]:
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering"))
    for path, value in changes.items():
        section, key = path.split("__")
        target = rules["tiers"][1] if section == "tier_1" else rules[section]
        target[key] = value
    return rules


async def _activate(
    client: AsyncClient, session: AsyncSession, settings: Settings, rules: dict[str, Any]
) -> None:
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/tiering/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    version = proposed.json()["version"]
    activated = await client.post(
        f"/api/v1/policies/tiering/versions/{version}/activate", headers=bearer(settings, approver)
    )
    assert activated.status_code == 200


async def test_a_stricter_policy_lowers_existing_tiers(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate_all_standing(session)
    await session.commit()
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1

    await _activate(client, session, settings, _tiering(tier_1__min_completed=2))
    activated = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.policy_activated")
        )
    ).one()
    await drain()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.UNRATED
    latest = (
        await session.scalars(select(StandingChange).order_by(StandingChange.created_at.desc()))
    ).first()
    assert latest is not None
    assert latest.trigger_event_id == activated.event_id
    assert latest.policy_version_id == (await active_tiering(session)).id


async def test_a_lower_threshold_verifies_skills_with_existing_evidence(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    session.add(
        SkillEvidence(
            worker_id=worker.id, skill_id=skill.id, engagement_id=engagement.id, reviewer_id=pm.id
        )
    )
    await session.commit()

    await _activate(
        client, session, settings, _tiering(skill_verification__min_distinct_reviewers=1)
    )
    await drain()

    claim = (await session.scalars(select(SkillClaim))).one()
    await session.refresh(claim)
    assert claim.verification_status is VerificationStatus.BONARDA_VERIFIED


async def test_a_matching_policy_does_not_touch_standing(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    # A worker who has never been recalculated: a tiering run would raise them
    # to tier_1. This makes the assertion meaningful — it would fail if the
    # kind filter in the handler were missing or wrong.
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching"))
    proposed = await client.post(
        "/api/v1/policies/matching/versions",
        json={"rules": rules},
        headers=bearer(settings, author),
    )
    assert proposed.status_code == 201
    version = proposed.json()["version"]
    activated = await client.post(
        f"/api/v1/policies/matching/versions/{version}/activate", headers=bearer(settings, approver)
    )
    assert activated.status_code == 200

    await drain()

    assert (await session.scalars(select(StandingChange))).all() == []
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.UNRATED


async def test_nightly_run_drops_a_tier_once_feedback_ages_out(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session)).id,
        completed_at=utcnow() - timedelta(days=30),
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    assert await recalculate_all_standing(session) == 1
    engagement.completed_at = utcnow() - timedelta(days=800)
    await session.commit()

    changed = await recalculate_all_standing(session)
    await session.commit()

    await session.refresh(worker)
    assert changed == 1
    assert worker.standing_tier is StandingTier.UNRATED


async def test_recalculate_all_does_not_deadlock_with_concurrent_skill_evidence(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recalculate_all locks the worker row, then (via promote_skills) locks
    the skill claim. A concurrent record_skill_evidence handler locks the
    claim first, then its evidence insert takes an FK lock on the worker row.
    Opposite lock orders across the two rows can deadlock unless the worker
    lock (lock_standing_tier) is FOR NO KEY UPDATE rather than FOR UPDATE.

    The two lock acquisitions are pinned with a two-phase barrier (rather than
    just an initial `asyncio.Event`) so the interleaving that causes the
    deadlock is forced, not merely possible: without it, recalculate_all's
    single-worker run is quick enough that record_skill_evidence's short
    transaction often finishes first, and the bug never gets exercised."""
    pm = await make_user(session, role=UserRole.PM)
    reviewer = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    project = await make_project(session)
    seed_engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    # Evidence already meets a threshold of 1, so promote_skills will lock
    # this claim as soon as recalculate_all reaches it.
    session.add(
        SkillEvidence(
            worker_id=worker.id,
            skill_id=skill.id,
            engagement_id=seed_engagement.id,
            reviewer_id=pm.id,
        )
    )
    await session.commit()
    new_engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)

    active = await active_tiering(session)
    policy = active.model_copy(
        update={
            "rules": active.rules.model_copy(
                update={
                    "skill_verification": active.rules.skill_verification.model_copy(
                        update={"min_distinct_reviewers": 1}
                    )
                }
            )
        }
    )

    worker_locked = asyncio.Event()
    claim_locked = asyncio.Event()
    real_lock_standing_tier = recalculation.lock_standing_tier
    real_lock_skill_claim = evidence.lock_skill_claim

    async def a_locks_worker_then_waits_for_b(
        s: AsyncSession, worker_id: UUID
    ) -> StandingTier | None:
        result = await real_lock_standing_tier(s, worker_id)
        worker_locked.set()
        await claim_locked.wait()
        return result

    async def b_waits_for_a_then_locks_claim(
        s: AsyncSession, worker_id: UUID, skill_id: UUID
    ) -> bool:
        await worker_locked.wait()
        result = await real_lock_skill_claim(s, worker_id, skill_id)
        claim_locked.set()
        return result

    monkeypatch.setattr(recalculation, "lock_standing_tier", a_locks_worker_then_waits_for_b)
    monkeypatch.setattr(evidence, "lock_skill_claim", b_waits_for_a_then_locks_claim)

    async def run_recalculate_all() -> None:
        async with sessionmaker() as s, s.begin():
            await recalculate_all(s, policy=policy, trigger_event_id=None)

    async def run_record_evidence() -> None:
        async with sessionmaker() as s, s.begin():
            await record_skill_evidence(
                s,
                engagement_id=new_engagement.id,
                worker_id=worker.id,
                reviewer_id=reviewer.id,
                skill_ids=[skill.id],
                min_reviewers=1,
            )

    await asyncio.wait_for(asyncio.gather(run_recalculate_all(), run_record_evidence()), timeout=10)

    claim = (
        await session.scalars(
            select(SkillClaim).where(
                SkillClaim.worker_id == worker.id, SkillClaim.skill_id == skill.id
            )
        )
    ).one()
    await session.refresh(claim)
    assert claim.verification_status is VerificationStatus.BONARDA_VERIFIED

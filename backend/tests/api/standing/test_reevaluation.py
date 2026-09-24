import copy
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import StandingTier, VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.standing.models import SkillEvidence, StandingChange
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
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching"))
    await client.post(
        "/api/v1/policies/matching/versions",
        json={"rules": rules},
        headers=bearer(settings, author),
    )
    await client.post(
        "/api/v1/policies/matching/versions/2/activate", headers=bearer(settings, approver)
    )

    await drain()

    assert (await session.scalars(select(StandingChange))).all() == []


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

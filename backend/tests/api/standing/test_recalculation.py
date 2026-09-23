import asyncio
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.engagements.models import Engagement
from app.modules.governance.service import active_tiering
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import StandingTier
from app.modules.passport.models import Worker
from app.modules.standing.models import StandingChange
from app.modules.standing.recalculation import recalculate
from tests.support import (
    POSITIVE_ANSWERS,
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def _completed_engagement(
    session: AsyncSession,
) -> tuple[UserAccount, Worker, Engagement]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    return pm, worker, engagement


async def test_positive_feedback_raises_the_tier_once(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _completed_engagement(session)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": POSITIVE_ANSWERS},
        headers=bearer(settings, pm),
    )
    feedback_event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "engagements.feedback_submitted")
        )
    ).one()
    await drain()

    assert response.status_code == 201
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1
    change = (await session.scalars(select(StandingChange))).one()
    policy = await active_tiering(session)
    assert (change.previous_tier, change.new_tier) == (StandingTier.UNRATED, StandingTier.TIER_1)
    assert change.policy_version_id == policy.id
    assert change.trigger_event_id == feedback_event.event_id
    assert change.actor_id is None
    assert change.contributing_factors["completed"] == 1
    assert change.contributing_factors["policy_version"] == 1
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "standing.changed"))
    ).one()
    assert (audit.target_id, audit.before, audit.after) == (
        worker.id,
        {"tier": "unrated"},
        {"tier": "tier_1", "policy_version": 1},
    )
    changed = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "standing.standing_changed")
        )
    ).one()
    assert changed.payload["new_tier"] == "tier_1"


async def test_negative_feedback_leaves_the_worker_unrated(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _completed_engagement(session)

    await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": {k: False for k in POSITIVE_ANSWERS}},
        headers=bearer(settings, pm),
    )
    await drain()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.UNRATED
    assert (await session.scalars(select(StandingChange))).all() == []


async def test_recalculating_again_records_nothing_new(session: AsyncSession) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    policy = await active_tiering(session)

    first = await recalculate(session, worker.id, policy=policy, trigger_event_id=None)
    second = await recalculate(session, worker.id, policy=policy, trigger_event_id=None)
    await session.commit()

    assert first is not None
    assert second is None
    assert len((await session.scalars(select(StandingChange))).all()) == 1


async def test_excluded_feedback_does_not_count(session: AsyncSession) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id, excluded=True)

    change = await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )

    assert change is None


async def test_concurrent_recalculations_record_one_change(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    async def run() -> None:
        async with sessionmaker() as s, s.begin():
            await recalculate(s, worker.id, policy=await active_tiering(s), trigger_event_id=None)

    await asyncio.gather(run(), run())

    assert len((await session.scalars(select(StandingChange))).all()) == 1


async def test_standing_changes_are_append_only(session: AsyncSession) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(update(StandingChange).values(override_reason="edited"))
    await session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(StandingChange))

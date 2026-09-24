from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.service import exclude_feedback
from app.modules.governance.service import active_tiering
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import StandingTier
from app.modules.passport.models import Worker
from app.modules.standing.models import StandingChange
from app.modules.standing.recalculation import recalculate
from tests.support import (
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

Drain = Callable[[], Awaitable[None]]


@dataclass
class Rated:
    worker: Worker
    account: UserAccount
    engagement: Engagement
    feedback: Feedback


async def _rated_worker(session: AsyncSession) -> Rated:
    """A tier_1 worker: one completed engagement with positive feedback."""
    pm = await make_user(session, role=UserRole.PM)
    worker, account = await make_worker(session)
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    feedback = await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1
    return Rated(worker=worker, account=account, engagement=engagement, feedback=feedback)


async def _decide(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    rated: Rated,
    target: tuple[str, UUID],
    resolution: str,
) -> None:
    target_type, target_id = target
    filed = await client.post(
        "/api/v1/disputes",
        json={
            "target_type": target_type,
            "target_id": str(target_id),
            "reason": "This record is not accurate.",
        },
        headers=bearer(settings, rated.account),
    )
    assert filed.status_code == 201, filed.json()
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    decided = await client.patch(
        f"/api/v1/disputes/{filed.json()['id']}",
        json={"resolution": resolution, "resolution_notes": "Reviewed with the project PM."},
        headers=bearer(settings, ops),
    )
    assert decided.status_code == 200, decided.json()


async def _change_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(StandingChange)) or 0)


async def test_an_upheld_feedback_dispute_stops_it_counting(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)

    await _decide(client, session, settings, rated, ("feedback", rated.feedback.id), "upheld")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is True
    assert rated.worker.standing_tier is StandingTier.UNRATED
    latest = (
        await session.scalars(select(StandingChange).order_by(StandingChange.created_at.desc()))
    ).first()
    resolved = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.dispute_resolved")
        )
    ).one()
    assert latest is not None
    assert (latest.new_tier, latest.trigger_event_id) == (StandingTier.UNRATED, resolved.event_id)
    audit = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "feedback.excluded_from_standing")
        )
    ).one()
    assert (audit.target_id, audit.reason) == (rated.engagement.id, "dispute_upheld")


async def test_a_rejected_dispute_changes_nothing(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)

    await _decide(client, session, settings, rated, ("feedback", rated.feedback.id), "rejected")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is False
    assert rated.worker.standing_tier is StandingTier.TIER_1


async def test_an_upheld_engagement_dispute_excludes_its_feedback(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)

    await _decide(client, session, settings, rated, ("engagement", rated.engagement.id), "upheld")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is True
    assert rated.worker.standing_tier is StandingTier.UNRATED


async def test_an_upheld_standing_change_dispute_leaves_the_data_alone(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)
    change = (await session.scalars(select(StandingChange))).one()

    await _decide(client, session, settings, rated, ("standing_change", change.id), "upheld")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is False
    assert rated.worker.standing_tier is StandingTier.TIER_1
    assert await _change_count(session) == 1


async def test_excluding_twice_changes_nothing_more(session: AsyncSession) -> None:
    rated = await _rated_worker(session)

    first = await exclude_feedback(session, rated.feedback.id, reason="dispute_upheld")
    second = await exclude_feedback(session, rated.feedback.id, reason="dispute_upheld")
    await session.commit()

    assert (first, second) == (True, False)
    audits = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "feedback.excluded_from_standing")
        )
    ).all()
    assert len(audits) == 1

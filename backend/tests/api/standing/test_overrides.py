from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import StandingTier
from app.modules.standing.models import StandingChange
from app.modules.standing.recalculation import recalculate
from app.modules.standing.service import recalculate_all_standing
from tests.support import (
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

REASON = "Verified strong references from two past clients."


def _url(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/standing-overrides"


async def test_people_ops_override_a_tier_with_a_reason(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url(worker.id), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["previous_tier"], body["new_tier"], body["automated"]) == (
        "unrated",
        "tier_2",
        False,
    )
    assert body["override_reason"] == REASON
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_2
    change = (await session.scalars(select(StandingChange))).one()
    assert (change.actor_id, change.contributing_factors["evaluated_tier"]) == (ops.id, "unrated")
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "standing.overridden"))
    ).one()
    assert (audit.reason, audit.before, audit.after) == (
        REASON,
        {"tier": "unrated"},
        {"tier": "tier_2", "evaluated_tier": "unrated"},
    )
    events = (await session.scalars(select(OutboxEvent.event_type))).all()
    assert events == ["standing.standing_changed"]
    explanation = (
        await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
    ).json()
    assert explanation["tier"] == "tier_2"
    assert explanation["history"][0]["automated"] is False


@pytest.mark.parametrize(
    ("role", "body", "status", "code"),
    [
        (UserRole.PM, {"tier": "tier_2", "reason": REASON}, 403, "permission_denied"),
        (UserRole.PEOPLE_OPS, {"tier": "tier_2", "reason": "short"}, 422, "validation_error"),
        (UserRole.PEOPLE_OPS, {"tier": "unrated", "reason": REASON}, 409, "standing_unchanged"),
    ],
)
async def test_overrides_are_refused_when_they_should_be(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    role: UserRole,
    body: dict[str, str],
    status: int,
    code: str,
) -> None:
    worker, _ = await make_worker(session)
    user = await make_user(session, role=role)

    response = await client.post(_url(worker.id), json=body, headers=bearer(settings, user))

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert (await session.scalars(select(StandingChange))).all() == []


async def test_overriding_an_unknown_worker_is_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url(uuid4()), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )

    assert (response.status_code, response.json()["code"]) == (404, "worker_not_found")


async def test_an_override_survives_the_nightly_re_evaluation(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await client.post(
        _url(worker.id), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )

    await recalculate_all_standing(session)
    await session.commit()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_2
    assert len((await session.scalars(select(StandingChange))).all()) == 1


async def test_an_override_yields_once_the_rules_verdict_moves(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)
    await client.post(
        _url(worker.id), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    change = await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1
    assert change is not None
    assert (change.previous_tier, change.new_tier, change.actor_id) == (
        StandingTier.TIER_2,
        StandingTier.TIER_1,
        None,
    )

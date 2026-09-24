"""FR-2.2, FR-3.1–3.3, NFR-5.1: feedback from distinct reviewers raises a
worker's tier and verifies a skill; People Ops tighten the policy with two
people; the worker's standing explanation shows every step."""

import copy
from collections.abc import Awaitable, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.identity.models import UserAccount
from app.modules.passport.models import Skill
from tests.support import (
    POSITIVE_ANSWERS,
    _seed_policy_rows,
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def test_feedback_raises_standing_and_a_policy_change_is_explained(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)

    async def review(pm: UserAccount, name: str) -> None:
        project = await make_project(session, staff=[pm], name=name)
        engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
        response = await client.post(
            f"/api/v1/engagements/{engagement.id}/feedback",
            json={
                "structured_answers": POSITIVE_ANSWERS,
                "skill_ids_demonstrated": [str(skill.id)],
            },
            headers=bearer(settings, pm),
        )
        assert response.status_code == 201
        await drain()

    async def standing() -> dict[str, Any]:
        response = await client.get(
            "/api/v1/workers/me/standing", headers=bearer(settings, account)
        )
        return response.json()

    # 1. One review: tier 1; the skill is not verified yet.
    await review(ama, "Volta")
    assert (await standing())["tier"] == "tier_1"
    me_after_first_review = await client.get(
        "/api/v1/workers/me", headers=bearer(settings, account)
    )
    assert me_after_first_review.json()["skills"][0]["verification_status"] == "self_reported"

    # 2. Two more reviews from a second PM: tier 2 and a verified skill.
    await review(kwame, "Tema")
    await review(kwame, "Kumasi")
    after = await standing()
    assert after["tier"] == "tier_2"
    me = await client.get("/api/v1/workers/me", headers=bearer(settings, account))
    assert me.json()["skills"][0]["verification_status"] == "bonarda_verified"

    # 3. People Ops tighten tier 2 to four engagements; a second person activates.
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering"))
    rules["tiers"][0]["min_completed"] = 4
    proposed = await client.post(
        "/api/v1/policies/tiering/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    self_activation = await client.post(
        "/api/v1/policies/tiering/versions/2/activate", headers=bearer(settings, author)
    )
    activated = await client.post(
        "/api/v1/policies/tiering/versions/2/activate", headers=bearer(settings, approver)
    )
    assert (proposed.status_code, self_activation.status_code, activated.status_code) == (
        201,
        403,
        200,
    )
    await drain()

    # 4. The worker drops to tier 1 under v2 and sees the whole history.
    final = await standing()
    assert (final["tier"], final["policy_version"]) == ("tier_1", 2)
    history = [(c["previous_tier"], c["new_tier"], c["policy_version"]) for c in final["history"]]
    # Newest first: the first review raised the tier on its own, the third
    # raised it again, and the v2 activation lowered it.
    assert history == [
        ("tier_2", "tier_1", 2),
        ("tier_1", "tier_2", 1),
        ("unrated", "tier_1", 1),
    ]

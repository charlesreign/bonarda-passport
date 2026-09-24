from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.service import active_tiering, policy_versions
from app.modules.passport.service import StandingTier, current_standing_tier
from app.modules.standing.repository import StandingChangeRepository
from app.modules.standing.rules import evaluate
from app.modules.standing.schemas import (
    StandingChangeRead,
    StandingExplanation,
    StandingFactors,
)

HISTORY_LIMIT = 50


async def standing_explanation(session: AsyncSession, worker_id: UUID) -> StandingExplanation:
    tier = await current_standing_tier(session, worker_id)
    if tier is None:
        raise NotFound("Worker not found", code="worker_not_found")
    policy = await active_tiering(session)
    evaluation = evaluate(await standing_records(session, worker_id), policy.rules, utcnow().date())
    changes = await StandingChangeRepository(session).list_for_worker(worker_id, HISTORY_LIMIT)
    versions = await policy_versions(
        session, [c.policy_version_id for c in changes if c.policy_version_id is not None]
    )
    return StandingExplanation(
        worker_id=worker_id,
        tier=tier,
        evaluated_tier=StandingTier(evaluation.tier),
        policy_version=policy.version,
        window_months=policy.rules.window_months,
        tiers=policy.rules.tiers,
        factors=StandingFactors(
            completed=evaluation.completed,
            distinct_reviewers=evaluation.distinct_reviewers,
            positive_ratio=round(evaluation.positive_ratio, 4),
            window_start=evaluation.window_start,
        ),
        history=[
            StandingChangeRead(
                previous_tier=c.previous_tier,
                new_tier=c.new_tier,
                factors=c.contributing_factors,
                policy_version=versions.get(c.policy_version_id) if c.policy_version_id else None,
                automated=c.actor_id is None,
                override_reason=c.override_reason,
                occurred_at=c.created_at,
            )
            for c in changes
        ],
    )

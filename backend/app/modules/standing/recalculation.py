from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.schemas import TieringPolicy
from app.modules.governance.service import active_tiering
from app.modules.passport.service import (
    StandingTier,
    lock_standing_tier,
    set_standing_tier,
    standing_worker_ids,
)
from app.modules.standing.evidence import promote_skills
from app.modules.standing.models import StandingChange
from app.modules.standing.repository import StandingChangeRepository
from app.modules.standing.rules import evaluate
from app.modules.standing.schemas import StandingChanged


async def recalculate(
    session: AsyncSession,
    worker_id: UUID,
    *,
    policy: TieringPolicy,
    trigger_event_id: UUID | None,
) -> StandingChange | None:
    """Re-evaluates one worker (spec §7.3). Writes a standing change only when
    the tier moves. The worker row lock serializes concurrent runs."""
    current = await lock_standing_tier(session, worker_id)
    if current is None:
        return None
    evaluation = evaluate(await standing_records(session, worker_id), policy.rules, utcnow().date())
    new_tier = StandingTier(evaluation.tier)
    if new_tier is current:
        return None
    changes = StandingChangeRepository(session)
    latest = await changes.latest_for_worker(worker_id)
    if (
        latest is not None
        and latest.actor_id is not None
        and latest.contributing_factors.get("evaluated_tier") == evaluation.tier
    ):
        # A People Ops override holds until the rules' own verdict moves.
        return None
    change = changes.add(
        StandingChange(
            worker_id=worker_id,
            previous_tier=current,
            new_tier=new_tier,
            contributing_factors={**evaluation.factors(), "policy_version": policy.version},
            policy_version_id=policy.id,
            trigger_event_id=trigger_event_id,
        )
    )
    await set_standing_tier(session, worker_id, new_tier)
    await session.flush()
    await write_audit(
        session,
        actor=None,
        action="standing.changed",
        target_type="worker",
        target_id=worker_id,
        before={"tier": current.value},
        after={"tier": new_tier.value, "policy_version": policy.version},
    )
    await emit_event(
        session,
        StandingChanged(
            aggregate_id=worker_id,
            previous_tier=current,
            new_tier=new_tier,
            policy_version=policy.version,
        ),
    )
    return change


async def recalculate_all(
    session: AsyncSession, *, policy: TieringPolicy, trigger_event_id: UUID | None
) -> int:
    """Re-evaluates every worker in the pool and promotes skills whose
    evidence meets the policy's threshold. Returns how many tiers changed."""
    changed = 0
    for worker_id in await standing_worker_ids(session):
        if await recalculate(session, worker_id, policy=policy, trigger_event_id=trigger_event_id):
            changed += 1
    await promote_skills(session, policy.rules.skill_verification.min_distinct_reviewers)
    return changed


async def recalculate_all_standing(session: AsyncSession) -> int:
    """Nightly: tiers follow the feedback window even when no event fires."""
    return await recalculate_all(
        session, policy=await active_tiering(session), trigger_event_id=None
    )

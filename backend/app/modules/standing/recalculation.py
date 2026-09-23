from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.schemas import TieringPolicy
from app.modules.passport.service import StandingTier, lock_standing_tier, set_standing_tier
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
    change = StandingChangeRepository(session).add(
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

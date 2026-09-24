"""Manual tier changes by People Ops (spec §7.2, §8.1)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.service import active_tiering
from app.modules.passport.service import lock_standing_tier, set_standing_tier
from app.modules.standing.models import StandingChange
from app.modules.standing.repository import StandingChangeRepository
from app.modules.standing.rules import evaluate
from app.modules.standing.schemas import StandingChanged, StandingOverrideCreate


async def override_standing(
    session: AsyncSession, actor: Actor, worker_id: UUID, data: StandingOverrideCreate
) -> StandingChange:
    """Stores the rules' verdict next to the override, so recalculation can
    leave the override alone until that verdict changes."""
    current = await lock_standing_tier(session, worker_id)
    if current is None:
        raise NotFound("Worker not found", code="worker_not_found")
    if data.tier is current:
        raise Conflict("The worker already has this tier", code="standing_unchanged")
    policy = await active_tiering(session)
    evaluation = evaluate(await standing_records(session, worker_id), policy.rules, utcnow().date())
    change = StandingChangeRepository(session).add(
        StandingChange(
            worker_id=worker_id,
            previous_tier=current,
            new_tier=data.tier,
            contributing_factors={
                **evaluation.factors(),
                "policy_version": policy.version,
                "evaluated_tier": evaluation.tier,
            },
            policy_version_id=policy.id,
            actor_id=actor.user_id,
            override_reason=data.reason,
        )
    )
    await set_standing_tier(session, worker_id, data.tier)
    await session.flush()
    await write_audit(
        session,
        actor=actor,
        action="standing.overridden",
        target_type="worker",
        target_id=worker_id,
        before={"tier": current.value},
        after={"tier": data.tier.value, "evaluated_tier": evaluation.tier},
        reason=data.reason,
    )
    await emit_event(
        session,
        StandingChanged(
            aggregate_id=worker_id,
            previous_tier=current,
            new_tier=data.tier,
            policy_version=policy.version,
        ),
    )
    return change

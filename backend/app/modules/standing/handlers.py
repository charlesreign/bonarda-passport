from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_event_id
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.schemas import FeedbackSubmitted
from app.modules.engagements.service import engagement_feedback_id, exclude_feedback
from app.modules.governance.schemas import DisputeResolved, PolicyActivated
from app.modules.governance.service import DisputeResolution, DisputeTargetType, active_tiering
from app.modules.standing.evidence import record_skill_evidence
from app.modules.standing.notifications import notify_standing_changed
from app.modules.standing.recalculation import recalculate, recalculate_all
from app.modules.standing.schemas import StandingChanged


def register(registry: HandlerRegistry, *, mailer: Mailer) -> None:
    async def recalculate_on_feedback(session: AsyncSession, payload: dict[str, Any]) -> None:
        await recalculate(
            session,
            UUID(payload["worker_id"]),
            policy=await active_tiering(session),
            trigger_event_id=get_event_id(),
        )

    registry.register(FeedbackSubmitted, "standing.recalculate", recalculate_on_feedback)

    async def record_evidence(session: AsyncSession, payload: dict[str, Any]) -> None:
        policy = await active_tiering(session)
        reviewer = payload.get("reviewer_id")
        await record_skill_evidence(
            session,
            engagement_id=UUID(payload["aggregate_id"]),
            worker_id=UUID(payload["worker_id"]),
            reviewer_id=UUID(reviewer) if reviewer else None,
            skill_ids=[UUID(s) for s in payload.get("skill_ids_demonstrated", [])],
            min_reviewers=policy.rules.skill_verification.min_distinct_reviewers,
        )

    registry.register(FeedbackSubmitted, "standing.record_skill_evidence", record_evidence)

    async def recalculate_on_policy(session: AsyncSession, payload: dict[str, Any]) -> None:
        if payload["kind"] != "tiering":
            return
        await recalculate_all(
            session, policy=await active_tiering(session), trigger_event_id=get_event_id()
        )

    registry.register(PolicyActivated, "standing.recalculate_all", recalculate_on_policy)

    async def apply_dispute_outcome(session: AsyncSession, payload: dict[str, Any]) -> None:
        """Spec §2.2 #8. An upheld standing-change dispute changes no data
        here: the rules are deterministic, so People Ops override the tier."""
        if payload["resolution"] != DisputeResolution.UPHELD.value:
            return
        target_id = UUID(payload["target_id"])
        if payload["target_type"] == DisputeTargetType.FEEDBACK.value:
            feedback_id: UUID | None = target_id
        elif payload["target_type"] == DisputeTargetType.ENGAGEMENT.value:
            feedback_id = await engagement_feedback_id(session, target_id)
        else:
            return
        if feedback_id is None or not await exclude_feedback(
            session, feedback_id, reason="dispute_upheld"
        ):
            return
        await recalculate(
            session,
            UUID(payload["worker_id"]),
            policy=await active_tiering(session),
            trigger_event_id=get_event_id(),
        )

    registry.register(DisputeResolved, "standing.apply_dispute_outcome", apply_dispute_outcome)

    async def notify_worker(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_standing_changed(
            session,
            mailer,
            UUID(payload["aggregate_id"]),
            previous=payload["previous_tier"],
            new=payload["new_tier"],
        )

    registry.register(StandingChanged, "standing.notify_worker", notify_worker)

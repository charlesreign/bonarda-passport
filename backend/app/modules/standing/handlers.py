from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_event_id
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.schemas import FeedbackSubmitted
from app.modules.governance.schemas import PolicyActivated
from app.modules.governance.service import active_tiering
from app.modules.standing.evidence import record_skill_evidence
from app.modules.standing.recalculation import recalculate, recalculate_all


def register(registry: HandlerRegistry) -> None:
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

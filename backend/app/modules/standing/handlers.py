from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_event_id
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.schemas import FeedbackSubmitted
from app.modules.governance.service import active_tiering
from app.modules.standing.recalculation import recalculate


def register(registry: HandlerRegistry) -> None:
    async def recalculate_on_feedback(session: AsyncSession, payload: dict[str, Any]) -> None:
        await recalculate(
            session,
            UUID(payload["worker_id"]),
            policy=await active_tiering(session),
            trigger_event_id=get_event_id(),
        )

    registry.register(FeedbackSubmitted, "standing.recalculate", recalculate_on_feedback)

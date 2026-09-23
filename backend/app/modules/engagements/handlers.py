from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.projects import end_staffing_for
from app.modules.identity.schemas import AccessRevoked


def register(registry: HandlerRegistry) -> None:
    async def end_staffing(session: AsyncSession, payload: dict[str, Any]) -> None:
        await end_staffing_for(
            session, UUID(payload["aggregate_id"]), reason=payload.get("reason", "access_revoked")
        )

    registry.register(AccessRevoked, "engagements.end_staffing_on_revocation", end_staffing)

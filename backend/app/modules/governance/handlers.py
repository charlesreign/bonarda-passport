from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.governance.notifications import notify_dispute_resolved
from app.modules.governance.schemas import DisputeResolved


def register(registry: HandlerRegistry, *, mailer: Mailer) -> None:
    async def notify_worker(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_dispute_resolved(session, mailer, UUID(payload["aggregate_id"]))

    registry.register(DisputeResolved, "governance.notify_worker", notify_worker)

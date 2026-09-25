from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.governance.disputes import scrub_dispute_text
from app.modules.governance.notifications import (
    notify_concentration_alert,
    notify_dispute_resolved,
)
from app.modules.governance.schemas import ConcentrationAlert, DisputeResolved


def register(registry: HandlerRegistry, *, mailer: Mailer) -> None:
    async def notify_worker(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_dispute_resolved(session, mailer, UUID(payload["aggregate_id"]))

    registry.register(DisputeResolved, "governance.notify_worker", notify_worker)

    async def scrub(session: AsyncSession, payload: dict[str, Any]) -> None:
        await scrub_dispute_text(session, worker_id=UUID(payload["aggregate_id"]))

    # By event type: governance imports no domain module but identity.
    registry.register("passport.worker_anonymized", "governance.scrub_dispute_text", scrub)

    async def alert_people_ops(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_concentration_alert(
            session,
            mailer,
            scope=payload["scope"],
            share=payload["share"],
            alert_share=payload["alert_share"],
        )

    registry.register(ConcentrationAlert, "governance.notify_concentration_alert", alert_people_ops)

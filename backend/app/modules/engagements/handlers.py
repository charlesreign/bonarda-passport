from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.contracts import send_contract, sync_worker_status
from app.modules.engagements.notifications import notify_engagement_confirmed, notify_feedback_due
from app.modules.engagements.payroll import signal_payroll
from app.modules.engagements.projects import end_staffing_for
from app.modules.engagements.schemas import (
    ContractDispatchRequested,
    EngagementActivated,
    EngagementCancelled,
    EngagementCompleted,
    EngagementCreated,
)
from app.modules.identity.schemas import AccessRevoked
from app.modules.integrations.service import EsignAdapter, PayrollAdapter


def register(
    registry: HandlerRegistry, *, esign: EsignAdapter, payroll: PayrollAdapter, mailer: Mailer
) -> None:
    async def end_staffing(session: AsyncSession, payload: dict[str, Any]) -> None:
        await end_staffing_for(
            session, UUID(payload["aggregate_id"]), reason=payload.get("reason", "access_revoked")
        )

    async def send(session: AsyncSession, payload: dict[str, Any]) -> None:
        await send_contract(session, esign, UUID(payload["aggregate_id"]))

    async def pay(session: AsyncSession, payload: dict[str, Any]) -> None:
        await signal_payroll(session, payroll, UUID(payload["aggregate_id"]))

    async def sync(session: AsyncSession, payload: dict[str, Any]) -> None:
        await sync_worker_status(session, UUID(payload["worker_id"]))

    registry.register(AccessRevoked, "engagements.end_staffing_on_revocation", end_staffing)
    registry.register(EngagementCreated, "engagements.send_contract", send)
    registry.register(ContractDispatchRequested, "engagements.resend_contract", send)
    registry.register(EngagementActivated, "engagements.signal_payroll", pay)
    registry.register(EngagementActivated, "engagements.sync_worker_status_on_activation", sync)
    registry.register(EngagementCancelled, "engagements.sync_worker_status_on_cancellation", sync)
    registry.register(EngagementCompleted, "engagements.sync_worker_status_on_completion", sync)

    async def confirm(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_engagement_confirmed(session, mailer, UUID(payload["aggregate_id"]))

    async def feedback_due(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_feedback_due(session, mailer, UUID(payload["aggregate_id"]))

    registry.register(EngagementActivated, "engagements.notify_worker", confirm)
    registry.register(EngagementCompleted, "engagements.notify_feedback_due", feedback_due)

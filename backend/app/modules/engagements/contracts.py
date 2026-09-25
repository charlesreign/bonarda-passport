from datetime import UTC, datetime, time
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.cancellation import cancel
from app.modules.engagements.engagements import EngagementService
from app.modules.engagements.enums import DECLINE_CAUSES, CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.engagements.schemas import (
    ContractDispatchRequested,
    ContractSigned,
    EngagementActivated,
    EsignWebhook,
)
from app.modules.identity.service import worker_contact
from app.modules.integrations.service import ContractDocument, EsignAdapter
from app.modules.passport.service import mark_worker_active, mark_worker_dormant, worker_name

log = structlog.get_logger(__name__)
_SENDABLE = (EngagementStatus.PENDING_SIGNATURE, EngagementStatus.AWAITING_SIGNATURE)


async def send_contract(session: AsyncSession, esign: EsignAdapter, engagement_id: UUID) -> None:
    """Outbox handler: sends (or re-sends) the contract. The adapter is
    idempotent per engagement, so a retried handler never makes a second envelope."""
    engagement = await EngagementRepository(session).get_for_update(engagement_id)
    if engagement is None or engagement.status not in _SENDABLE:
        log.info("engagements.contract_not_sent", engagement_id=str(engagement_id))
        return
    project = await ProjectRepository(session).get(engagement.project_id)
    contact = await worker_contact(session, engagement.worker_id)
    name = await worker_name(session, engagement.worker_id)
    if contact is None:
        # The worker's account is gone (erased or anonymized): nobody can sign,
        # so cancel rather than retry into the dead-letter list.
        await cancel(
            session,
            engagement,
            CancelCause.WORKER_ACCOUNT_MISSING,
            actor=None,
            action="engagement.cancelled",
            reason="worker_account_missing",
        )
        return
    if project is None or name is None:
        raise RuntimeError(f"engagement {engagement_id} is missing its project or worker")
    envelope_id = await esign.send_contract(
        ContractDocument(
            engagement_id=engagement.id,
            signer_name=name,
            signer_email=contact.email,
            project_name=project.name,
            start_date=engagement.start_date,
            end_date=engagement.end_date,
            rate=engagement.rate,
            currency=engagement.currency,
            work_mode=engagement.work_mode.value,
            scope=engagement.contract_terms["scope"],
            access_notes=engagement.contract_terms.get("access_notes"),
        )
    )
    engagement.esign_envelope_id = envelope_id
    engagement.status = EngagementStatus.AWAITING_SIGNATURE
    engagement.contract_sent_at = utcnow()
    engagement.stuck_flagged_at = None
    await write_audit(
        session,
        actor=None,
        action="engagement.contract_sent",
        target_type="engagement",
        target_id=engagement.id,
        after={"envelope_id": envelope_id},
    )


async def activate(session: AsyncSession, engagement: Engagement) -> None:
    """Billable start (spec §2.2 #9): contract signed and start date reached.
    Billing starts at whichever came last, not when the hourly job ran."""
    if engagement.signed_at is None:
        raise RuntimeError(f"engagement {engagement.id} is activated before it was signed")
    start_of_day = datetime.combine(engagement.start_date, time.min, tzinfo=UTC)
    engagement.status = EngagementStatus.ACTIVE
    engagement.billable_start_at = max(engagement.signed_at, start_of_day)
    await write_audit(
        session,
        actor=None,
        action="engagement.activated",
        target_type="engagement",
        target_id=engagement.id,
        after={"billable_start_at": engagement.billable_start_at.isoformat()},
    )
    await emit_event(
        session,
        EngagementActivated(
            aggregate_id=engagement.id,
            worker_id=engagement.worker_id,
            project_id=engagement.project_id,
        ),
    )


async def activate_due(session: AsyncSession) -> int:
    """Hourly: signed engagements whose start date has arrived."""
    due = await EngagementRepository(session).due_signed(utcnow().date())
    for engagement in due:
        await activate(session, engagement)
    return len(due)


async def sync_worker_status(session: AsyncSession, worker_id: UUID) -> None:
    if await EngagementRepository(session).active_count(worker_id) > 0:
        await mark_worker_active(session, worker_id)
    else:
        await mark_worker_dormant(session, worker_id, since=utcnow().date())


class ContractService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engagements = EngagementRepository(session)

    async def handle_webhook(self, event: EsignWebhook) -> None:
        engagement = await self.engagements.get_by_envelope_for_update(event.envelope_id)
        if engagement is None:
            raise NotFound("Unknown envelope", code="envelope_not_found")
        if event.event == "signed":
            await self._signed(engagement)
        else:
            await self._declined(engagement)

    async def _signed(self, engagement: Engagement) -> None:
        if engagement.status is not EngagementStatus.AWAITING_SIGNATURE:
            if engagement.cancel_cause in DECLINE_CAUSES:
                # The worker declined, yet the provider reports a signature: the
                # decline stands, but People Ops should see the stray envelope.
                log.warning("engagements.signed_after_decline", engagement_id=str(engagement.id))
                await write_audit(
                    self.session,
                    actor=None,
                    action="engagement.signed_after_decline",
                    target_type="engagement",
                    target_id=engagement.id,
                )
            return  # replayed or out-of-order: nothing else to do
        engagement.status = EngagementStatus.SIGNED
        engagement.signed_at = utcnow()
        engagement.stuck_flagged_at = None
        await write_audit(
            self.session,
            actor=None,
            action="engagement.contract_signed",
            target_type="engagement",
            target_id=engagement.id,
        )
        await emit_event(self.session, ContractSigned(aggregate_id=engagement.id))
        if engagement.start_date <= utcnow().date():
            await activate(self.session, engagement)

    async def _declined(self, engagement: Engagement) -> None:
        if engagement.status not in _SENDABLE:
            return
        await cancel(
            self.session,
            engagement,
            CancelCause.ESIGN_DECLINED,
            actor=None,
            action="engagement.contract_declined",
        )

    async def request_retry(self, actor: Actor, engagement_id: UUID) -> Engagement:
        engagement = await EngagementService(self.session).managed(actor, engagement_id)
        if engagement.status not in _SENDABLE:
            raise Conflict(
                "Only an unsigned contract can be re-sent", code="contract_not_retryable"
            )
        engagement.stuck_flagged_at = None
        await write_audit(
            self.session,
            actor=actor,
            action="engagement.contract_retry_requested",
            target_type="engagement",
            target_id=engagement.id,
        )
        await emit_event(self.session, ContractDispatchRequested(aggregate_id=engagement.id))
        return engagement


async def void_contract(
    session: AsyncSession, esign: EsignAdapter, engagement_id: UUID, envelope_id: str
) -> None:
    """Outbox handler: withdraws a declined offer's envelope. A failure
    retries through the outbox, so a provider outage never blocks a decline."""
    engagement = await EngagementRepository(session).get_for_update(engagement_id)
    if engagement is None or engagement.void_requested_at is not None:
        return
    await esign.void(envelope_id)
    engagement.void_requested_at = utcnow()
    await write_audit(
        session,
        actor=None,
        action="engagement.contract_voided",
        target_type="engagement",
        target_id=engagement.id,
        after={"envelope_id": envelope_id},
    )

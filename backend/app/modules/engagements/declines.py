"""The worker's side of an offer: declining it, and who may see a decline
afterwards (offer-decline spec §4–§5). Declines are recorded, never scored."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.engagements.cancellation import cancel
from app.modules.engagements.enums import (
    DECLINABLE_STATUSES,
    CancelCause,
    EngagementStatus,
)
from app.modules.engagements.models import Engagement
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import ContractVoidRequested, DeclineRequest


class DeclineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engagements = EngagementRepository(session)

    async def decline(
        self, actor: Actor, worker_id: UUID, engagement_id: UUID, data: DeclineRequest
    ) -> Engagement:
        # The row lock orders us against the e-sign webhook and send_contract:
        # whichever commits first wins (spec §4 Races).
        engagement = await self.engagements.get_for_update(engagement_id)
        if engagement is None or engagement.worker_id != worker_id:
            raise NotFound("Engagement not found", code="engagement_not_found")
        if engagement.cancel_cause is CancelCause.WORKER_DECLINED:
            return engagement  # a replay: the first answer stands
        if engagement.status not in DECLINABLE_STATUSES:
            raise Conflict("This offer can no longer be declined", code="engagement_not_declinable")
        envelope_id = (
            engagement.esign_envelope_id
            if engagement.status is EngagementStatus.AWAITING_SIGNATURE
            else None
        )
        engagement.decline_reason = data.reason
        engagement.decline_note = data.note
        await cancel(
            self.session,
            engagement,
            CancelCause.WORKER_DECLINED,
            actor=actor,
            action="engagement.declined",
            after={"reason": data.reason.value},  # never the note: erasure clears one place
        )
        if envelope_id is not None:
            await emit_event(
                self.session,
                ContractVoidRequested(aggregate_id=engagement.id, envelope_id=envelope_id),
            )
        return engagement

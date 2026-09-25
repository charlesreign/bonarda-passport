"""The worker's side of an offer: declining it, and who may see a decline
afterwards (offer-decline spec §4–§5). Declines are recorded, never scored."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.enums import UserRole
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.engagements.cancellation import cancel
from app.modules.engagements.enums import (
    DECLINABLE_STATUSES,
    CancelCause,
    EngagementStatus,
)
from app.modules.engagements.models import Engagement
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.engagements.schemas import ContractVoidRequested, DeclineRequest
from app.modules.identity.service import Visibility


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


_FULL_VIEWERS = frozenset({UserRole.PEOPLE_OPS, UserRole.ADMIN})


def decline_visible_to(
    actor: Actor,
    level: Visibility,
    engagement: Engagement,
    staffed_project_ids: Collection[UUID],
) -> bool:
    """The worker, People Ops, admin and the offering project's PMs see a
    decline. Nobody else learns of it, so it cannot become an informal
    penalty on the worker (offer-decline spec §5)."""
    if level is Visibility.SELF or actor.role in _FULL_VIEWERS:
        return True
    return engagement.project_id in staffed_project_ids


async def staffed_project_ids(session: AsyncSession, actor: Actor) -> set[UUID]:
    if actor.role is not UserRole.PM:
        return set()
    return {p.id for p in await ProjectRepository(session).list_staffed_by(actor.user_id)}


async def scrub_decline_notes(session: AsyncSession, *, worker_id: UUID) -> int:
    """Erasure (spec §6.3): the note is personal free text; the reason and
    cause are structural and stay. Returns how many notes were removed."""
    engagements = await EngagementRepository(session).with_decline_note(worker_id)
    for engagement in engagements:
        engagement.decline_note = None
        await write_audit(
            session,
            actor=None,
            action="engagement.decline_note_removed",
            target_type="engagement",
            target_id=engagement.id,
            reason="worker_anonymized",
        )
    return len(engagements)

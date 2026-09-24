from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict
from app.core.outbox.writer import emit_event
from app.modules.engagements.engagements import EngagementService
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import FeedbackCreate, FeedbackSubmitted
from app.modules.passport.service import claimed_skill_ids

_EXISTS_DETAIL = "Feedback was already submitted for this engagement"
_EXISTS_CODE = "feedback_exists"


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engagements = EngagementRepository(session)

    async def submit(
        self, actor: Actor, engagement_id: UUID, data: FeedbackCreate
    ) -> tuple[Engagement, Feedback]:
        engagement = await EngagementService(self.session).managed(actor, engagement_id)
        if engagement.status is not EngagementStatus.COMPLETED:
            raise Conflict(
                "Feedback opens when the engagement is completed", code="engagement_not_completed"
            )
        if engagement.id in await self.engagements.feedback_for([engagement.id]):
            raise Conflict(_EXISTS_DETAIL, code=_EXISTS_CODE)
        claimed = await claimed_skill_ids(self.session, engagement.worker_id)
        if set(data.skill_ids_demonstrated) - claimed:
            raise BadRequest(
                "Demonstrated skills must be skills the worker lists", code="skill_not_claimed"
            )
        answers = data.structured_answers.model_dump()
        try:
            async with self.session.begin_nested():
                feedback = self.engagements.add_feedback(
                    Feedback(
                        engagement_id=engagement.id,
                        reviewer_id=actor.user_id,
                        structured_answers=answers,
                        free_text=data.free_text,
                        skill_ids_demonstrated=data.skill_ids_demonstrated,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_feedback_engagement_id":
                raise
            raise Conflict(_EXISTS_DETAIL, code=_EXISTS_CODE) from exc
        # Structured answers only: free text is personal data (spec §6.3).
        await write_audit(
            self.session,
            actor=actor,
            action="feedback.submitted",
            target_type="engagement",
            target_id=engagement.id,
            after={"structured_answers": answers},
        )
        await emit_event(
            self.session,
            FeedbackSubmitted(
                aggregate_id=engagement.id,
                worker_id=engagement.worker_id,
                reviewer_id=actor.user_id,
                skill_ids_demonstrated=data.skill_ids_demonstrated,
            ),
        )
        return engagement, feedback


async def exclude_feedback(session: AsyncSession, feedback_id: UUID, *, reason: str) -> bool:
    """Spec §2.2 #8: an upheld dispute stops the record counting toward
    standing. True only if this call changed it."""
    feedback = await EngagementRepository(session).feedback_for_update(feedback_id)
    if feedback is None or feedback.excluded_from_standing:
        return False
    feedback.excluded_from_standing = True
    await write_audit(
        session,
        actor=None,
        action="feedback.excluded_from_standing",
        target_type="engagement",
        target_id=feedback.engagement_id,
        before={"excluded_from_standing": False},
        after={"excluded_from_standing": True},
        reason=reason,
    )
    return True

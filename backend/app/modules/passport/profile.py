from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound, UnprocessableEntity
from app.core.outbox.writer import emit_event
from app.modules.identity.service import Visibility, account_contact
from app.modules.passport.dependencies import WorkerActor
from app.modules.passport.enums import AvailabilityStatus, OnboardingState
from app.modules.passport.models import Worker
from app.modules.passport.queries import profile_gaps
from app.modules.passport.repository import SkillClaimRepository, WorkerRepository
from app.modules.passport.schemas import (
    WorkerDetail,
    WorkerSelf,
    WorkerSkill,
    WorkerSummary,
    WorkerUpdate,
    WorkerUpdated,
)


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workers = WorkerRepository(session)
        self.claims = SkillClaimRepository(session)

    async def _worker(self, worker_id: UUID) -> Worker:
        worker = await self.workers.get(worker_id)
        if worker is None:
            raise NotFound("Worker not found", code="worker_not_found")
        return worker

    async def _skills(self, worker_id: UUID) -> list[WorkerSkill]:
        return [
            WorkerSkill(
                skill_id=skill.id, slug=skill.slug, verification_status=claim.verification_status
            )
            for claim, skill in await self.claims.list_for_worker(worker_id)
        ]

    async def view(
        self, actor: Actor, worker_id: UUID, level: Visibility
    ) -> WorkerSummary | WorkerDetail | WorkerSelf:
        worker = await self._worker(worker_id)
        summary: dict[str, Any] = {
            "id": worker.id,
            "full_name": worker.full_name,
            "worker_type": worker.worker_type,
            "status": worker.status,
            "data_region": worker.data_region,
            "base_location": worker.base_location,
            "availability_status": worker.availability_status,
            "available_from": worker.available_from,
            "standing_tier": worker.standing_tier,
            "skills": await self._skills(worker.id),
        }
        if level is Visibility.SUMMARY:
            return WorkerSummary(**summary)
        detail = summary | {
            "languages": worker.languages,
            "onboarding_state": worker.onboarding_state,
            "dormant_since": worker.dormant_since,
            "created_at": worker.created_at,
        }
        if level is Visibility.SELF:
            contact = await account_contact(self.session, actor.user_id)
            return WorkerSelf(**detail, email=contact.email, locale=contact.locale)
        return WorkerDetail(**detail)

    async def view_self(self, who: WorkerActor) -> WorkerSelf:
        view = await self.view(who.actor, who.worker_id, Visibility.SELF)
        assert isinstance(view, WorkerSelf)
        return view

    async def update_self(self, who: WorkerActor, data: WorkerUpdate) -> WorkerSelf:
        worker = await self._worker(who.worker_id)
        changes = data.model_dump(exclude_unset=True)
        status = changes.get("availability_status", worker.availability_status)
        if (
            "availability_status" in changes
            and status is not AvailabilityStatus.AVAILABLE_FROM
            and changes.get("available_from") is not None
        ):
            raise UnprocessableEntity(
                "available_from needs availability_status=available_from",
                code="availability_status_mismatch",
            )
        if "availability_status" in changes and status is not AvailabilityStatus.AVAILABLE_FROM:
            changes["available_from"] = None
        available_from = changes.get("available_from", worker.available_from)
        if status is AvailabilityStatus.AVAILABLE_FROM and available_from is None:
            raise UnprocessableEntity(
                "available_from is required with availability_status=available_from",
                code="availability_date_required",
            )
        if available_from is not None and status is not AvailabilityStatus.AVAILABLE_FROM:
            raise UnprocessableEntity(
                "available_from needs availability_status=available_from",
                code="availability_status_mismatch",
            )
        for field, value in changes.items():
            setattr(worker, field, value)
        if changes:
            await emit_event(
                self.session, WorkerUpdated(aggregate_id=worker.id, fields=sorted(changes))
            )
        return await self.view_self(who)

    async def complete_onboarding(self, who: WorkerActor) -> WorkerSelf:
        """Gates first-time engagements (FR-5.1). Idempotent."""
        worker = await self._worker(who.worker_id)
        if worker.onboarding_state is not OnboardingState.PROFILE_COMPLETE:
            missing = await profile_gaps(self.session, worker)
            if missing:
                raise Conflict(
                    f"Complete your profile first: {', '.join(missing)}",
                    code="onboarding_incomplete",
                )
            worker.onboarding_state = OnboardingState.PROFILE_COMPLETE
            await write_audit(
                self.session,
                actor=who.actor,
                action="worker.onboarding_completed",
                target_type="worker",
                target_id=worker.id,
            )
            await emit_event(
                self.session, WorkerUpdated(aggregate_id=worker.id, fields=["onboarding_state"])
            )
        return await self.view_self(who)

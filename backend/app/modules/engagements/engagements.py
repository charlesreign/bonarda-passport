import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementPath, EngagementStatus, ProjectStatus
from app.modules.engagements.models import Engagement, Project
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.engagements.schemas import (
    ContractTerms,
    EngagementCreate,
    EngagementCreated,
    ReactivationCreate,
    ReactivationPrefill,
)
from app.modules.passport.service import engagement_readiness, worker_region

_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")

_CONSTRAINT_CODES = {
    "uq_engagements_open_worker_project": (
        "This worker already has an open engagement on this project",
        "engagement_already_open",
    ),
    "uq_engagements_idempotency_key": (
        "This Idempotency-Key was already used for a different request",
        "idempotency_key_reused",
    ),
}


class EngagementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.engagements = EngagementRepository(session)

    async def staffed_project(self, actor: Actor, project_id: UUID) -> Project:
        project = await self.projects.get(project_id)
        if project is None or not await self.projects.is_staffed(project.id, actor.user_id):
            raise NotFound("Project not found", code="project_not_found")
        return project

    async def managed(self, actor: Actor, engagement_id: UUID) -> Engagement:
        """An engagement the actor may act on: a PM staffed on its project."""
        engagement = await self.engagements.get_for_update(engagement_id)
        if engagement is None or not await self.projects.is_staffed(
            engagement.project_id, actor.user_id
        ):
            raise NotFound("Engagement not found", code="engagement_not_found")
        return engagement

    async def create(
        self,
        actor: Actor,
        worker_id: UUID,
        data: EngagementCreate,
        *,
        path: EngagementPath,
        idempotency_key: str | None = None,
        prefilled_from: UUID | None = None,
    ) -> Engagement:
        project = await self.staffed_project(actor, data.project_id)
        if project.status is not ProjectStatus.ACTIVE:
            raise Conflict("This project is closed", code="project_closed")
        readiness = await engagement_readiness(self.session, worker_id)
        if readiness is None:
            raise NotFound("Worker not found", code="worker_not_found")
        if not readiness.onboarding_complete or readiness.gaps:
            missing = ", ".join(readiness.gaps) or "onboarding"
            raise Conflict(f"Worker profile incomplete: {missing}", code="worker_not_ready")
        region = await worker_region(self.session, worker_id)
        if region is None or not (
            region.cross_region_ok or region.data_region == project.data_region
        ):
            raise Conflict(
                "Worker is not eligible for this project's region", code="region_not_eligible"
            )
        has_history = await self.engagements.has_history(worker_id)
        if path is EngagementPath.FIRST_TIME and has_history:
            raise Conflict(
                "This worker has engaged with Bonarda before; reactivate them instead",
                code="use_reactivation",
            )
        if path is EngagementPath.REACTIVATION and not has_history:
            raise Conflict("No earlier engagement to reactivate", code="no_prior_engagement")
        if await self.engagements.open_for(worker_id, project.id) is not None:
            detail, code = _CONSTRAINT_CODES["uq_engagements_open_worker_project"]
            raise Conflict(detail, code=code)
        try:
            async with self.session.begin_nested():
                engagement = self.engagements.add(
                    Engagement(
                        worker_id=worker_id,
                        project_id=project.id,
                        path=path,
                        status=EngagementStatus.PENDING_SIGNATURE,
                        start_date=data.start_date,
                        end_date=data.end_date,
                        rate=data.rate,
                        currency=data.currency,
                        work_mode=data.work_mode,
                        location=data.location,
                        contract_terms=data.contract_terms.model_dump(),
                        prefilled_from_engagement_id=prefilled_from,
                        confirmed_at=utcnow(),
                        idempotency_key=idempotency_key,
                        created_by_id=actor.user_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            mapped = _CONSTRAINT_CODES.get(violated_constraint(exc) or "")
            if mapped is None:
                raise
            raise Conflict(mapped[0], code=mapped[1]) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="engagement.created",
            target_type="engagement",
            target_id=engagement.id,
            after={
                "path": path.value,
                "project_id": str(project.id),
                "start_date": engagement.start_date.isoformat(),
            },
        )
        await emit_event(
            self.session,
            EngagementCreated(
                aggregate_id=engagement.id,
                worker_id=worker_id,
                project_id=project.id,
                path=path,
            ),
        )
        return engagement

    async def prefill(self, actor: Actor, worker_id: UUID, project_id: UUID) -> ReactivationPrefill:
        await self.staffed_project(actor, project_id)
        latest = await self.engagements.latest_for_worker(worker_id)
        if latest is None:
            raise NotFound("No earlier engagement to reactivate", code="no_prior_engagement")
        days = None
        if latest.billable_start_at is not None:
            days = round(
                (latest.billable_start_at - latest.confirmed_at).total_seconds() / 86400, 2
            )
        return ReactivationPrefill(
            prefilled_from_engagement_id=latest.id,
            rate=latest.rate,
            currency=latest.currency,
            work_mode=latest.work_mode,
            location=latest.location,
            contract_terms=ContractTerms.model_validate(latest.contract_terms),
            last_days_to_start=days,
        )

    async def reactivate(
        self,
        actor: Actor,
        worker_id: UUID,
        data: ReactivationCreate,
        idempotency_key: str | None,
    ) -> tuple[Engagement, bool]:
        """Returns (engagement, replayed). A replay of the same PM's key for the
        same worker returns the original engagement (spec §8.4)."""
        if idempotency_key is None or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise BadRequest(
                "Send an Idempotency-Key header of 8-64 letters, digits, '-' or '_'",
                code="idempotency_key_required",
            )
        existing = await self.engagements.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.worker_id == worker_id and existing.created_by_id == actor.user_id:
                return existing, True
            detail, code = _CONSTRAINT_CODES["uq_engagements_idempotency_key"]
            raise Conflict(detail, code=code)
        if data.prefilled_from_engagement_id is not None:
            source = await self.engagements.get(data.prefilled_from_engagement_id)
            if source is None or source.worker_id != worker_id:
                raise BadRequest(
                    "The prefill source must be one of this worker's engagements",
                    code="invalid_prefill_source",
                )
        terms = EngagementCreate.model_validate(
            data.model_dump(exclude={"prefilled_from_engagement_id"})
        )
        try:
            engagement = await self.create(
                actor,
                worker_id,
                terms,
                path=EngagementPath.REACTIVATION,
                idempotency_key=idempotency_key,
                prefilled_from=data.prefilled_from_engagement_id,
            )
        except Conflict as exc:
            if exc.code not in ("idempotency_key_reused", "engagement_already_open"):
                raise
            # Lost a race against a concurrent replay of the same key: the
            # winner's row may not have been visible when we checked above.
            existing = await self.engagements.get_by_idempotency_key(idempotency_key)
            if (
                existing is not None
                and existing.worker_id == worker_id
                and existing.created_by_id == actor.user_id
            ):
                return existing, True
            raise
        return engagement, False

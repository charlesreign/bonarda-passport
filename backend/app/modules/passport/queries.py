"""Read and status functions other modules use through passport.service."""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.writer import emit_event
from app.modules.passport.enums import ConsentPurpose, OnboardingState, WorkerStatus
from app.modules.passport.models import Skill, Worker
from app.modules.passport.repository import (
    ConsentRepository,
    SkillClaimRepository,
    WorkerRepository,
)
from app.modules.passport.schemas import EngagementReadiness, WorkerRegion, WorkerUpdated


async def existing_skill_ids(session: AsyncSession, skill_ids: Iterable[UUID]) -> set[UUID]:
    ids = list(skill_ids)
    if not ids:
        return set()
    return set((await session.scalars(select(Skill.id).where(Skill.id.in_(ids)))).all())


_NOT_SURFACED = (WorkerStatus.OFFBOARDED, WorkerStatus.ANONYMIZED)


async def worker_region(session: AsyncSession, worker_id: UUID) -> WorkerRegion | None:
    """Region facts for visibility and matching; None if the worker is
    unknown or no longer part of the talent pool."""
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status in _NOT_SURFACED:
        return None
    consent = await ConsentRepository(session).get(worker_id, ConsentPurpose.CROSS_REGION_MATCHING)
    return WorkerRegion(
        data_region=worker.data_region,
        cross_region_ok=consent is not None and consent.granted,
    )


async def profile_gaps(session: AsyncSession, worker: Worker) -> list[str]:
    """What a worker still needs before they can be engaged (FR-5.1)."""
    gaps = []
    if not worker.base_location:
        gaps.append("base_location")
    if not worker.languages:
        gaps.append("languages")
    if not await SkillClaimRepository(session).list_for_worker(worker.id):
        gaps.append("skills")
    return gaps


async def engagement_readiness(
    session: AsyncSession, worker_id: UUID
) -> EngagementReadiness | None:
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status in _NOT_SURFACED:
        return None
    return EngagementReadiness(
        onboarding_complete=worker.onboarding_state is OnboardingState.PROFILE_COMPLETE,
        gaps=await profile_gaps(session, worker),
    )


async def worker_name(session: AsyncSession, worker_id: UUID) -> str | None:
    worker = await WorkerRepository(session).get(worker_id)
    return worker.full_name if worker is not None else None


async def mark_worker_active(session: AsyncSession, worker_id: UUID) -> None:
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status is not WorkerStatus.DORMANT:
        return
    worker.status = WorkerStatus.ACTIVE
    worker.dormant_since = None
    await emit_event(session, WorkerUpdated(aggregate_id=worker_id, fields=["status"]))


async def mark_worker_dormant(session: AsyncSession, worker_id: UUID, *, since: date) -> None:
    """FR-9.7: not engaged is dormant, not deleted."""
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status is not WorkerStatus.ACTIVE:
        return
    worker.status = WorkerStatus.DORMANT
    worker.dormant_since = since
    await emit_event(session, WorkerUpdated(aggregate_id=worker_id, fields=["status"]))

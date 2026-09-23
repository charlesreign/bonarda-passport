"""Read and status functions other modules use through passport.service."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.passport.enums import ConsentPurpose, WorkerStatus
from app.modules.passport.models import Skill
from app.modules.passport.repository import ConsentRepository, WorkerRepository
from app.modules.passport.schemas import WorkerRegion


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

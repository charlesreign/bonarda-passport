"""Erasure (spec §6.3): the worker row stays for structural history (dates,
tiers, outcomes), but everything that identifies the person goes. Other
modules scrub their own data on WorkerAnonymized."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.passport.enums import AvailabilityStatus, WorkerStatus
from app.modules.passport.repository import ConsentRepository, WorkerRepository
from app.modules.passport.schemas import WorkerAnonymized

ANONYMIZED_NAME = "Anonymized worker"


async def anonymize_worker(
    session: AsyncSession, worker_id: UUID, *, actor: Actor | None, reason: str
) -> bool:
    """True if this call anonymized the worker; False if already anonymized.
    A worker on an active engagement cannot be erased until it ends."""
    worker = await WorkerRepository(session).get_for_update(worker_id)
    if worker is None:
        raise NotFound("Worker not found", code="worker_not_found")
    if worker.status is WorkerStatus.ANONYMIZED:
        return False
    if worker.status is WorkerStatus.ACTIVE:
        raise Conflict(
            "This worker is on an active engagement; erase them once it ends",
            code="worker_active",
        )
    previous = worker.status
    worker.full_name = ANONYMIZED_NAME
    worker.base_location = None
    worker.languages = []
    worker.availability_status = AvailabilityStatus.UNAVAILABLE
    worker.available_from = None
    worker.status = WorkerStatus.ANONYMIZED
    await ConsentRepository(session).delete_for_worker(worker_id)
    # No personal data in the audit row: it outlives the erasure.
    await write_audit(
        session,
        actor=actor,
        action="worker.anonymized",
        target_type="worker",
        target_id=worker_id,
        before={"status": previous.value},
        after={"status": WorkerStatus.ANONYMIZED.value},
        reason=reason,
    )
    await emit_event(session, WorkerAnonymized(aggregate_id=worker_id))
    return True


async def retention_due(session: AsyncSession, cutoff: date) -> list[UUID]:
    return await WorkerRepository(session).dormant_before(cutoff)


async def tier_distribution(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Region -> tier -> count for the talent pool, plus an "ORG" total."""
    result: dict[str, dict[str, int]] = {"ORG": {}}
    for region, tier, count in await WorkerRepository(session).tier_counts():
        result.setdefault(region, {})[tier] = count
        result["ORG"][tier] = result["ORG"].get(tier, 0) + count
    return result


async def is_surfaced(session: AsyncSession, worker_id: UUID) -> bool:
    """Whether PMs may see this worker at all. Anonymized and offboarded
    workers are visible to People Ops only (structural history)."""
    worker = await WorkerRepository(session).get(worker_id)
    return worker is not None and worker.status not in (
        WorkerStatus.ANONYMIZED,
        WorkerStatus.OFFBOARDED,
    )

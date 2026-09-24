from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.engagements.service import engagement_activity
from app.modules.passport.service import all_worker_ids, roster_snapshot
from app.modules.roster.repository import RosterRepository


async def _lock_worker_refresh(session: AsyncSession, worker_id: UUID) -> None:
    """Serializes refreshes of one worker for the rest of the transaction, so
    a slower refresh never overwrites a newer snapshot with an older one."""
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(worker_id), 0)))
    )


async def refresh_worker(session: AsyncSession, worker_id: UUID) -> bool:
    """Rebuilds one roster row from its sources. Returns False if the worker
    no longer exists (the row is removed)."""
    await _lock_worker_refresh(session, worker_id)
    repo = RosterRepository(session)
    snapshot = await roster_snapshot(session, worker_id)
    if snapshot is None:
        await repo.delete(worker_id)
        return False
    activity = await engagement_activity(session, worker_id, utcnow().date())
    await repo.upsert(
        {
            "worker_id": snapshot.worker_id,
            "display_name": snapshot.display_name,
            "status": snapshot.status.value,
            "onboarding_state": snapshot.onboarding_state.value,
            "data_region": snapshot.data_region,
            "cross_region_ok": snapshot.cross_region_ok,
            "standing_tier": snapshot.standing_tier.value,
            "skill_ids": snapshot.skill_ids,
            "verified_skill_ids": snapshot.verified_skill_ids,
            "base_location": snapshot.base_location,
            "availability_status": snapshot.availability_status.value,
            "available_from": snapshot.available_from,
            "engagements_total": activity.total,
            "engagements_last_12m": activity.last_12m,
            "last_engaged_on": activity.last_engaged_on,
            "refreshed_at": utcnow(),
        }
    )
    return True


async def rebuild_all(session: AsyncSession) -> int:
    """Nightly drift repair (spec §6.5). Workers are visited in id order."""
    worker_ids = await all_worker_ids(session)
    for worker_id in worker_ids:
        await refresh_worker(session, worker_id)
    return len(worker_ids)

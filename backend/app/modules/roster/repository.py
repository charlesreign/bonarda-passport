from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roster.models import RosterProfile


class RosterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, worker_id: UUID) -> RosterProfile | None:
        return await self.session.get(RosterProfile, worker_id)

    async def upsert(self, values: dict[str, Any]) -> None:
        changes = {k: v for k, v in values.items() if k != "worker_id"}
        await self.session.execute(
            pg_insert(RosterProfile)
            .values(**values)
            .on_conflict_do_update(index_elements=[RosterProfile.worker_id], set_=changes)
        )

    async def delete(self, worker_id: UUID) -> None:
        await self.session.execute(
            delete(RosterProfile).where(RosterProfile.worker_id == worker_id)
        )

    async def eligible(
        self,
        data_region: str,
        *,
        skill_ids: Sequence[UUID] = (),
        availability: str | None = None,
        location: str | None = None,
        q: str | None = None,
    ) -> list[RosterProfile]:
        """Summary-eligible workers for a project in `data_region` (spec §7.1,
        §8.5): in the talent pool, onboarded, and in the region or consented."""
        stmt = select(RosterProfile).where(
            RosterProfile.status.in_(("active", "dormant")),
            RosterProfile.onboarding_state == "profile_complete",
            or_(
                RosterProfile.data_region == data_region,
                RosterProfile.cross_region_ok.is_(True),
            ),
        )
        if skill_ids:
            stmt = stmt.where(RosterProfile.skill_ids.contains(list(skill_ids)))
        if availability is not None:
            stmt = stmt.where(RosterProfile.availability_status == availability)
        if location:
            stmt = stmt.where(RosterProfile.base_location.icontains(location, autoescape=True))
        if q:
            stmt = stmt.where(RosterProfile.display_name.icontains(q, autoescape=True))
        return list((await self.session.scalars(stmt)).all())

from typing import Any
from uuid import UUID

from sqlalchemy import delete
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

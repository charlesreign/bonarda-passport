from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.standing.models import StandingChange


class StandingChangeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, change: StandingChange) -> StandingChange:
        self.session.add(change)
        return change

    async def list_for_worker(self, worker_id: UUID, limit: int) -> list[StandingChange]:
        stmt = (
            select(StandingChange)
            .where(StandingChange.worker_id == worker_id)
            .order_by(StandingChange.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

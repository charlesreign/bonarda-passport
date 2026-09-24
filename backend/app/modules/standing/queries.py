"""Read functions other modules use through standing.service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.standing.models import StandingChange


async def standing_change_worker_id(session: AsyncSession, change_id: UUID) -> UUID | None:
    return await session.scalar(
        select(StandingChange.worker_id).where(StandingChange.id == change_id)
    )

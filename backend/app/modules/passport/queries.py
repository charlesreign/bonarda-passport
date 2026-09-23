"""Read and status functions other modules use through passport.service."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.passport.models import Skill


async def existing_skill_ids(session: AsyncSession, skill_ids: Iterable[UUID]) -> set[UUID]:
    ids = list(skill_ids)
    if not ids:
        return set()
    return set((await session.scalars(select(Skill.id).where(Skill.id.in_(ids)))).all())

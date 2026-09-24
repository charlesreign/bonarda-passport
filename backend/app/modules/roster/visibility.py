from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.enums import UserRole
from app.modules.engagements.service import staffed_project_ids
from app.modules.identity.service import Visibility
from app.modules.roster.repository import FirstShotRepository


async def first_shot_relationship(
    session: AsyncSession, actor: Actor, worker_id: UUID
) -> Visibility:
    """Spec §7.1: shortlisting, contacting or engaging a first-shot worker on a
    project the PM staffs gives detail; passing does not. Staffing is read live."""
    if actor.role is not UserRole.PM:
        return Visibility.NONE
    projects = await staffed_project_ids(session, actor.user_id)
    if await FirstShotRepository(session).has_detail_outcome(worker_id, projects):
        return Visibility.DETAIL
    return Visibility.NONE

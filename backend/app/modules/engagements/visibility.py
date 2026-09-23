from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.enums import UserRole
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.identity.service import Visibility
from app.modules.passport.service import worker_region


async def project_relationship(session: AsyncSession, actor: Actor, worker_id: UUID) -> Visibility:
    """Spec §7.1 for PMs: detail through an engagement on a project they staff,
    summary through a staffed project the worker is region-eligible for."""
    if actor.role is not UserRole.PM:
        return Visibility.NONE
    staffed = await ProjectRepository(session).list_staffed_by(actor.user_id)
    if not staffed:
        return Visibility.NONE
    if await EngagementRepository(session).worker_engaged_on(worker_id, [p.id for p in staffed]):
        return Visibility.DETAIL
    region = await worker_region(session, worker_id)
    if region is None:
        return Visibility.NONE
    if region.cross_region_ok or any(p.data_region == region.data_region for p in staffed):
        return Visibility.SUMMARY
    return Visibility.NONE

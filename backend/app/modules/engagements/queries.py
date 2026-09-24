"""Read functions other modules use through engagements.service."""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.enums import HISTORY_STATUSES, EngagementStatus
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.repository import ProjectRepository
from app.modules.engagements.schemas import EngagementActivity, ProjectContext, StandingRecord


async def standing_records(session: AsyncSession, worker_id: UUID) -> list[StandingRecord]:
    """Completed engagements with their feedback, if any, for the standing engine."""
    stmt = (
        select(
            Engagement.id,
            Engagement.completed_at,
            Engagement.end_date,
            Engagement.start_date,
            Feedback.reviewer_id,
            Feedback.structured_answers,
            Feedback.excluded_from_standing,
        )
        .outerjoin(Feedback, Feedback.engagement_id == Engagement.id)
        .where(Engagement.worker_id == worker_id, Engagement.status == EngagementStatus.COMPLETED)
    )
    return [
        StandingRecord(
            engagement_id=row.id,
            completed_on=row.completed_at.date()
            if row.completed_at is not None
            else (row.end_date or row.start_date),
            reviewer_id=row.reviewer_id,
            answers=row.structured_answers,
            excluded=bool(row.excluded_from_standing),
        )
        for row in await session.execute(stmt)
    ]


async def engagement_activity(
    session: AsyncSession, worker_id: UUID, today: date
) -> EngagementActivity:
    """`total` counts every history engagement, including one signed with a
    future start date. `last_12m` and `last_engaged_on` only look at work
    that has actually started (start_date <= today), so a future-dated
    signed engagement does not inflate the recent count or set a
    last-engaged date that hasn't happened yet."""
    since = today - timedelta(days=365)
    total, last_12m, last_on = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Engagement.start_date >= since, Engagement.start_date <= today),
                func.max(Engagement.start_date).filter(Engagement.start_date <= today),
            ).where(Engagement.worker_id == worker_id, Engagement.status.in_(HISTORY_STATUSES))
        )
    ).one()
    return EngagementActivity(total=total, last_12m=last_12m, last_engaged_on=last_on)


async def engagement_worker_id(session: AsyncSession, engagement_id: UUID) -> UUID | None:
    return await session.scalar(select(Engagement.worker_id).where(Engagement.id == engagement_id))


async def feedback_worker_id(session: AsyncSession, feedback_id: UUID) -> UUID | None:
    return await session.scalar(
        select(Engagement.worker_id)
        .join(Feedback, Feedback.engagement_id == Engagement.id)
        .where(Feedback.id == feedback_id)
    )


async def staffed_project(
    session: AsyncSession, user_id: UUID, project_id: UUID
) -> ProjectContext | None:
    """The project, if this user actively staffs it as an active PM."""
    projects = ProjectRepository(session)
    project = await projects.get(project_id)
    if project is None or not await projects.is_staffed(project.id, user_id):
        return None
    return ProjectContext(
        id=project.id,
        name=project.name,
        data_region=project.data_region,
        required_skill_ids=project.required_skill_ids,
        starts_on=project.starts_on,
        status=project.status,
    )


async def staffed_project_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    return [p.id for p in await ProjectRepository(session).list_staffed_by(user_id)]


async def engagement_feedback_id(session: AsyncSession, engagement_id: UUID) -> UUID | None:
    return await session.scalar(select(Feedback.id).where(Feedback.engagement_id == engagement_id))

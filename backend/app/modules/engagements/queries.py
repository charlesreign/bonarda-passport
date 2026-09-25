"""Read functions other modules use through engagements.service."""

from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.enums import HISTORY_STATUSES, EngagementStatus
from app.modules.engagements.models import Engagement, Feedback, Project
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


async def concentration_counts(
    session: AsyncSession, since: date, until: date, repeat_min: int
) -> dict[str, tuple[int, int]]:
    """scope ("ORG" or region) -> (engagements, engagements going to workers
    with at least `repeat_min` engagements in the window). Work that started
    in the window and actually happened (signed or later) counts."""
    rows = (
        await session.execute(
            select(Engagement.worker_id, Project.data_region)
            .join(Project, Project.id == Engagement.project_id)
            .where(
                Engagement.status.in_(HISTORY_STATUSES),
                Engagement.start_date >= since,
                Engagement.start_date <= until,
            )
        )
    ).all()
    per_worker = Counter(worker_id for worker_id, _ in rows)
    totals: dict[str, list[int]] = {}
    for worker_id, region in rows:
        for scope in ("ORG", region):
            counts = totals.setdefault(scope, [0, 0])
            counts[0] += 1
            if per_worker[worker_id] >= repeat_min:
                counts[1] += 1
    return {scope: (total, repeat) for scope, (total, repeat) in totals.items()}


async def project_regions(session: AsyncSession, project_ids: Iterable[UUID]) -> dict[UUID, str]:
    ids = list(project_ids)
    if not ids:
        return {}
    rows = await session.execute(select(Project.id, Project.data_region).where(Project.id.in_(ids)))
    return {project_id: region for project_id, region in rows}

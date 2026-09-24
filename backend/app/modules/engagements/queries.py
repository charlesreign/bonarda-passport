"""Read functions other modules use through engagements.service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.schemas import StandingRecord


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

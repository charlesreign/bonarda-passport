from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.service import standing_records
from tests.support import make_engagement, make_feedback, make_project, make_user, make_worker


async def test_standing_records_are_completed_engagements_with_their_feedback(
    session: AsyncSession,
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session)
    project = await make_project(session)
    reviewed = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=reviewed.id, reviewer_id=pm.id, excluded=True)
    unreviewed = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        completed_at=utcnow() - timedelta(days=40),
    )
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.ACTIVE
    )

    records = {r.engagement_id: r for r in await standing_records(session, worker.id)}

    assert set(records) == {reviewed.id, unreviewed.id}
    assert records[reviewed.id].reviewer_id == pm.id
    assert records[reviewed.id].excluded is True
    assert records[reviewed.id].answers is not None
    assert records[unreviewed.id].answers is None
    assert records[unreviewed.id].excluded is False
    assert records[unreviewed.id].completed_on == (utcnow() - timedelta(days=40)).date()


async def test_completion_date_falls_back_to_end_then_start_date(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    project = await make_project(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, end_date=date(2026, 2, 1)
    )
    engagement.completed_at = None
    await session.commit()

    (record,) = await standing_records(session, worker.id)

    assert record.completed_on == date(2026, 2, 1)

from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Feedback
from tests.support import bearer, make_engagement, make_project, make_user, make_worker


def _url(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/engagements"


async def test_worker_sees_their_history_newest_first_with_feedback(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    project = await make_project(session)
    older = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, start_date=date(2025, 3, 1)
    )
    newer = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        start_date=date(2026, 2, 1),
        status=EngagementStatus.CANCELLED,
    )
    session.add(
        Feedback(
            engagement_id=older.id,
            structured_answers={
                "delivered_on_agreed_dates": True,
                "handled_scope_changes_without_escalation": True,
                "would_reengage": True,
            },
            free_text="Great work on the pipeline.",
        )
    )
    await session.commit()

    response = await client.get(_url(worker.id), headers=bearer(settings, account))

    body = response.json()
    assert [e["id"] for e in body] == [str(newer.id), str(older.id)]
    assert body[1]["rate"] == "450.00"
    assert body[1]["contract_terms"]["scope"] == "Build the data pipeline"
    assert body[1]["feedback"]["free_text"] == "Great work on the pipeline."
    assert body[0]["feedback"] is None
    assert body[0]["stuck"] is False


async def test_people_ops_sees_any_workers_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    worker, _ = await make_worker(session)
    await make_engagement(session, worker_id=worker.id, project_id=(await make_project(session)).id)

    response = await client.get(_url(worker.id), headers=bearer(settings, ops))

    assert len(response.json()) == 1


async def test_summary_level_pm_cannot_read_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH")
    await make_engagement(session, worker_id=worker.id, project_id=(await make_project(session)).id)

    response = await client.get(_url(worker.id), headers=bearer(settings, pm))

    assert response.status_code == 404
    assert response.json()["code"] == "worker_not_found"

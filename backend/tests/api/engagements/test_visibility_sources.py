from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.models import ProjectStaff
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import ConsentPurpose, WorkerStatus
from app.modules.passport.models import Consent
from tests.support import bearer, make_engagement, make_project, make_user, make_worker


async def _view(
    client: AsyncClient, settings: Settings, pm: UserAccount, worker_id: UUID
) -> str | None:
    response = await client.get(f"/api/v1/workers/{worker_id}", headers=bearer(settings, pm))
    return response.json().get("view") if response.status_code == 200 else None


async def test_pm_on_a_project_in_the_workers_region_sees_the_summary(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH")

    assert await _view(client, settings, pm, worker.id) == "summary"


async def test_other_region_needs_cross_region_consent(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="EU")
    worker, _ = await make_worker(session, data_region="GH")

    before = await _view(client, settings, pm, worker.id)
    session.add(
        Consent(
            worker_id=worker.id,
            purpose=ConsentPurpose.CROSS_REGION_MATCHING,
            granted=True,
            legal_basis="consent",
            granted_at=utcnow(),
        )
    )
    await session.commit()
    after = await _view(client, settings, pm, worker.id)

    assert (before, after) == (None, "summary")


async def test_engagement_on_a_staffed_project_gives_detail(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="EU")
    worker, _ = await make_worker(session, data_region="GH")
    await make_engagement(session, worker_id=worker.id, project_id=project.id)

    assert await _view(client, settings, pm, worker.id) == "detail"


async def test_ended_staffing_removes_visibility_immediately(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH")
    await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await session.execute(update(ProjectStaff).values(active_to=utcnow()))
    await session.commit()

    assert await _view(client, settings, pm, worker.id) is None


@pytest.mark.parametrize("status", [WorkerStatus.ANONYMIZED, WorkerStatus.OFFBOARDED])
async def test_offboarded_or_anonymized_workers_are_not_surfaced_by_region(
    client: AsyncClient, session: AsyncSession, settings: Settings, status: WorkerStatus
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH", status=status)

    assert await _view(client, settings, pm, worker.id) is None


async def test_unstaffed_pm_sees_nothing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session, data_region="GH")

    assert await _view(client, settings, pm, worker.id) is None

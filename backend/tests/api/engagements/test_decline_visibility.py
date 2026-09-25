from dataclasses import dataclass
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.identity.models import UserAccount
from tests.support import bearer, make_engagement, make_project, make_ready_worker, make_user


@dataclass
class Scene:
    worker_account: UserAccount
    offering_pm: UserAccount
    other_pm: UserAccount
    people_ops: UserAccount
    admin: UserAccount
    worker_id: str
    completed: Engagement
    in_app: Engagement
    at_provider: Engagement
    account_missing: Engagement


@pytest.fixture
async def scene(session: AsyncSession) -> Scene:
    """One worker: a completed engagement on project B (so B's PM has detail
    visibility), an in-app and an e-sign decline on project A, and an
    account-missing cancellation on project B."""
    offering_pm = await make_user(session, role=UserRole.PM)
    other_pm = await make_user(session, role=UserRole.PM)
    project_a = await make_project(session, staff=[offering_pm], name="Project A")
    project_b = await make_project(session, staff=[other_pm], name="Project B")
    worker, account = await make_ready_worker(session)
    past = utcnow().date() - timedelta(days=90)
    completed = await make_engagement(
        session, worker_id=worker.id, project_id=project_b.id, start_date=past
    )
    in_app = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project_a.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.WORKER_DECLINED,
    )
    in_app.decline_note = "The dates clash with another contract"
    at_provider = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project_a.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.ESIGN_DECLINED,
    )
    account_missing = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project_b.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.WORKER_ACCOUNT_MISSING,
    )
    await session.commit()
    return Scene(
        worker_account=account,
        offering_pm=offering_pm,
        other_pm=other_pm,
        people_ops=await make_user(session, role=UserRole.PEOPLE_OPS),
        admin=await make_user(session, role=UserRole.ADMIN),
        worker_id=str(worker.id),
        completed=completed,
        in_app=in_app,
        at_provider=at_provider,
        account_missing=account_missing,
    )


async def _list(
    client: AsyncClient, settings: Settings, scene: Scene, viewer: UserAccount
) -> dict[str, dict[str, object]]:
    response = await client.get(
        f"/api/v1/workers/{scene.worker_id}/engagements", headers=bearer(settings, viewer)
    )
    assert response.status_code == 200
    return {row["id"]: row for row in response.json()}


@pytest.mark.parametrize("viewer", ["worker_account", "offering_pm", "people_ops", "admin"])
async def test_the_worker_the_offering_pm_and_people_ops_see_declines_in_full(
    client: AsyncClient, settings: Settings, scene: Scene, viewer: str
) -> None:
    rows = await _list(client, settings, scene, getattr(scene, viewer))

    in_app = rows[str(scene.in_app.id)]["decline"]
    at_provider = rows[str(scene.at_provider.id)]["decline"]
    assert isinstance(in_app, dict) and isinstance(at_provider, dict)
    assert (in_app["cause"], in_app["reason"], in_app["note"]) == (
        "worker_declined",
        "other",
        "The dates clash with another contract",
    )
    assert in_app["declined_at"] is not None
    assert (at_provider["cause"], at_provider["reason"]) == ("esign_declined", None)
    assert rows[str(scene.completed.id)]["decline"] is None


async def test_a_pm_on_another_project_never_sees_a_decline(
    client: AsyncClient, settings: Settings, scene: Scene
) -> None:
    rows = await _list(client, settings, scene, scene.other_pm)

    assert set(rows) == {str(scene.completed.id), str(scene.account_missing.id)}
    assert rows[str(scene.account_missing.id)]["decline"] is None

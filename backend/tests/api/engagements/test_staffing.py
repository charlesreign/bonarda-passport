from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import ProjectStaff
from tests.support import bearer, make_project, make_user

Drain = Callable[[], Awaitable[None]]


def _url(project_id: object) -> str:
    return f"/api/v1/projects/{project_id}/staff"


async def _active_staff(session: AsyncSession, project_id: object) -> set[object]:
    rows = await session.scalars(
        select(ProjectStaff.user_account_id).where(
            ProjectStaff.project_id == project_id, ProjectStaff.active_to.is_(None)
        )
    )
    return set(rows.all())


async def test_people_ops_replaces_the_staff_list(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(kwame.id), str(kwame.id)]},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 200
    assert response.json()["staff_ids"] == [str(kwame.id)]
    assert await _active_staff(session, project.id) == {kwame.id}
    ended = (
        await session.scalars(select(ProjectStaff).where(ProjectStaff.user_account_id == ama.id))
    ).one()
    assert ended.active_to is not None
    audit = (await session.scalars(select(AuditLog))).one()
    assert audit.action == "project.staff_changed"
    assert (audit.before, audit.after) == ({"staff": [str(ama.id)]}, {"staff": [str(kwame.id)]})


async def test_staffed_pm_adds_a_colleague(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(ama.id), str(kwame.id)]},
        headers=bearer(settings, ama),
    )

    assert response.status_code == 200
    assert await _active_staff(session, project.id) == {ama.id, kwame.id}


async def test_unstaffed_pm_cannot_see_or_change_the_project(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    outsider = await make_user(session, role=UserRole.PM)
    project = await make_project(session)

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(outsider.id)]},
        headers=bearer(settings, outsider),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "project_not_found"


async def test_staff_must_be_active_pms(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    finance = await make_user(session, role=UserRole.FINANCE)
    project = await make_project(session)

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(finance.id)]},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "staff_not_active_pm"


async def test_unchanged_staff_list_writes_no_audit(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])

    await client.put(
        _url(project.id), json={"user_account_ids": [str(ama.id)]}, headers=bearer(settings, ama)
    )

    assert (await session.scalars(select(AuditLog))).all() == []


async def test_scim_deactivation_ends_the_pms_staffing(
    client: AsyncClient, session: AsyncSession, drain: Drain
) -> None:
    ama = await make_user(session, role=UserRole.PM, oidc_subject="kc-ama")
    project = await make_project(session, staff=[ama])

    await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
        headers={
            "Authorization": "Bearer scim-test-token",
            "Content-Type": "application/scim+json",
        },
    )
    await drain()

    assert await _active_staff(session, project.id) == set()
    removed = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "project.staff_removed"))
    ).one()
    assert (removed.target_id, removed.reason) == (project.id, "deactivated")

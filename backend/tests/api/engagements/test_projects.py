from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import Project
from app.modules.passport.models import Skill
from tests.support import bearer, make_project, make_user

URL = "/api/v1/projects"


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"name": "Project Volta", "data_region": "GH"}
    body.update(overrides)
    return body


async def test_pm_creates_a_project_and_is_staffed_on_it(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.commit()

    response = await client.post(
        URL,
        json=_body(client_name="Accra Water", required_skill_ids=[str(skill.id)]),
        headers=bearer(settings, pm),
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["name"], body["data_region"], body["status"]) == ("Project Volta", "GH", "active")
    assert body["staff_ids"] == [str(pm.id)]
    assert body["required_skill_ids"] == [str(skill.id)]
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id) == ("project.created", pm.id)


async def test_people_ops_project_starts_unstaffed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(URL, json=_body(), headers=bearer(settings, ops))

    assert response.json()["staff_ids"] == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"data_region": "ZZ"}, "unknown_data_region"),
        ({"required_skill_ids": [str(uuid4())]}, "unknown_skill"),
    ],
)
async def test_unknown_region_or_skill_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    overrides: dict[str, object],
    code: str,
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=_body(**overrides), headers=bearer(settings, pm))

    assert response.status_code == 400
    assert response.json()["code"] == code
    assert (await session.scalars(select(Project))).all() == []


@pytest.mark.parametrize(
    "overrides",
    [{"starts_on": "2026-11-01", "ends_on": "2026-10-01"}, {"name": ""}, {"data_region": "gh"}],
)
async def test_invalid_projects_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, overrides: dict[str, object]
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=_body(**overrides), headers=bearer(settings, pm))

    assert response.status_code == 422


@pytest.mark.parametrize("role", [UserRole.WORKER, UserRole.FINANCE])
async def test_only_staff_roles_create_projects(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    user = await make_user(session, role=role)

    response = await client.post(URL, json=_body(), headers=bearer(settings, user))

    assert response.status_code == 403


async def test_pm_lists_and_reads_only_projects_they_staff(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    mine = await make_project(session, staff=[pm], name="Mine")
    theirs = await make_project(session, name="Theirs")
    headers = bearer(settings, pm)

    listed = await client.get(URL, headers=headers)
    own = await client.get(f"{URL}/{mine.id}", headers=headers)
    other = await client.get(f"{URL}/{theirs.id}", headers=headers)

    assert [p["name"] for p in listed.json()] == ["Mine"]
    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json()["code"] == "project_not_found"


async def test_people_ops_sees_every_project(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await make_project(session, name="One")
    await make_project(session, name="Two")

    response = await client.get(URL, headers=bearer(settings, ops))

    assert sorted(p["name"] for p in response.json()) == ["One", "Two"]


async def test_workers_cannot_list_projects(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker = await make_user(session, role=UserRole.WORKER)

    response = await client.get(URL, headers=bearer(settings, worker))

    assert response.status_code == 403

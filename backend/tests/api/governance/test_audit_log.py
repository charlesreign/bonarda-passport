from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.pagination import encode_cursor
from tests.support import bearer, make_user

URL = "/api/v1/governance/audit-log"


async def _audit(session: AsyncSession, target_id: UUID, *actions: str) -> None:
    for action in actions:
        await write_audit(
            session, actor=None, action=action, target_type="worker", target_id=target_id
        )
    await session.commit()


async def test_people_ops_read_one_records_trail_newest_first(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    worker_id = uuid4()
    await _audit(session, worker_id, "worker.invited", "consent.granted")
    await _audit(session, uuid4(), "worker.invited")

    response = await client.get(
        URL,
        params={"target_type": "worker", "target_id": str(worker_id)},
        headers=bearer(settings, ops),
    )

    body = response.json()
    assert response.status_code == 200
    assert [e["action"] for e in body["items"]] == ["consent.granted", "worker.invited"]
    assert {e["target_id"] for e in body["items"]} == {str(worker_id)}
    assert body["next_cursor"] is None


async def test_pages_follow_on_without_overlap(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _audit(session, uuid4(), "a.one", "a.two", "a.three")
    headers = bearer(settings, ops)

    first = (await client.get(URL, params={"limit": 2}, headers=headers)).json()
    second = (
        await client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)
    ).json()

    assert [e["action"] for e in first["items"]] == ["a.three", "a.two"]
    assert [e["action"] for e in second["items"]] == ["a.one"]
    assert second["next_cursor"] is None


async def test_filters_by_action(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _audit(session, uuid4(), "consent.granted", "worker.invited", "consent.granted")

    response = await client.get(
        URL, params={"action": "consent.granted"}, headers=bearer(settings, ops)
    )

    assert [e["action"] for e in response.json()["items"]] == ["consent.granted"] * 2


@pytest.mark.parametrize(
    ("role", "status"), [(UserRole.ADMIN, 200), (UserRole.PM, 403), (UserRole.FINANCE, 403)]
)
async def test_only_audit_readers_see_the_trail(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole, status: int
) -> None:
    user = await make_user(session, role=role)

    response = await client.get(URL, headers=bearer(settings, user))

    assert response.status_code == status


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        encode_cursor({"x": "1"}),
        encode_cursor({"id": "abc"}),
        encode_cursor({"id": "0"}),
        encode_cursor({"id": "9" * 30}),
    ],
)
async def test_a_tampered_cursor_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, cursor: str
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(URL, params={"cursor": cursor}, headers=bearer(settings, ops))

    assert (response.status_code, response.json()["code"]) == (400, "invalid_cursor")


async def test_target_id_needs_a_target_type(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(
        URL, params={"target_id": str(uuid4())}, headers=bearer(settings, ops)
    )

    assert (response.status_code, response.json()["code"]) == (400, "target_type_required")

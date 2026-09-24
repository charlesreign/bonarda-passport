import copy
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.governance.models import PolicyConfig
from app.modules.governance.service import active_tiering
from tests.support import _seed_policy_rows, bearer, make_user


def _url(kind: str, suffix: str = "") -> str:
    return f"/api/v1/policies/{kind}/versions{suffix}"


def _tiering(**tier_2: Any) -> dict[str, Any]:
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering"))
    rules["tiers"][0].update(tier_2)
    return rules


async def _versions(session: AsyncSession, kind: str) -> dict[int, str]:
    rows = await session.execute(
        select(PolicyConfig.version, PolicyConfig.status).where(PolicyConfig.kind == kind)
    )
    return {version: status.value for version, status in rows}


async def test_people_ops_lists_the_seeded_policy(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(_url("tiering"), headers=bearer(settings, ops))

    body = response.json()
    assert response.status_code == 200
    assert [(p["version"], p["status"]) for p in body] == [(1, "active")]
    assert body[0]["rules"]["window_months"] == 24


async def test_propose_creates_the_next_draft_version(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url("tiering"),
        json={"rules": _tiering(min_completed=4), "notes": "Stricter tier 2"},
        headers=bearer(settings, ops),
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["version"], body["status"], body["created_by_id"]) == (2, "draft", str(ops.id))
    assert await _versions(session, "tiering") == {1: "active", 2: "draft"}
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.after) == ("policy.proposed", {"kind": "tiering", "version": 2})


@pytest.mark.parametrize(
    ("kind", "rules", "status", "code"),
    [
        ("tiering", {"window_months": 24}, 422, "invalid_policy_rules"),
        ("tiering", {**_tiering(), "surprise": 1}, 422, "invalid_policy_rules"),
        ("concentration", {"threshold": 0.4}, 400, "policy_kind_not_supported"),
    ],
)
async def test_invalid_proposals_are_rejected(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    kind: str,
    rules: dict[str, Any],
    status: int,
    code: str,
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(_url(kind), json={"rules": rules}, headers=bearer(settings, ops))

    assert response.status_code == status
    assert response.json()["code"] == code
    assert await _versions(session, kind) == ({1: "active"} if kind == "tiering" else {})


async def test_the_author_cannot_activate_their_own_policy(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await client.post(_url("tiering"), json={"rules": _tiering()}, headers=bearer(settings, ops))

    response = await client.post(_url("tiering", "/2/activate"), headers=bearer(settings, ops))

    assert response.status_code == 403
    assert response.json()["code"] == "policy_self_activation"
    assert await _versions(session, "tiering") == {1: "active", 2: "draft"}


async def test_a_second_person_activates_and_the_old_version_retires(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    await client.post(_url("tiering"), json={"rules": _tiering()}, headers=bearer(settings, author))

    response = await client.post(_url("tiering", "/2/activate"), headers=bearer(settings, approver))

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["activated_by_id"]) == ("active", str(approver.id))
    assert await _versions(session, "tiering") == {1: "retired", 2: "active"}
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "governance.policy_activated"
    assert (event.payload["kind"], event.payload["version"], event.payload["previous_version"]) == (
        "tiering",
        2,
        1,
    )
    activated = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "policy.activated"))
    ).one()
    assert (activated.actor_id, activated.before, activated.after) == (
        approver.id,
        {"active_version": 1},
        {"active_version": 2},
    )
    assert (await active_tiering(session)).version == 2


@pytest.mark.parametrize(
    ("version", "status", "code"), [(1, 409, "policy_not_draft"), (9, 404, "policy_not_found")]
)
async def test_only_existing_drafts_can_be_activated(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    version: int,
    status: int,
    code: str,
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url("tiering", f"/{version}/activate"), headers=bearer(settings, ops)
    )

    assert (response.status_code, response.json()["code"]) == (status, code)


@pytest.mark.parametrize("role", [UserRole.PM, UserRole.ADMIN, UserRole.WORKER])
async def test_only_people_ops_manage_policies(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    user = await make_user(session, role=role)

    proposed = await client.post(
        _url("tiering"), json={"rules": _tiering()}, headers=bearer(settings, user)
    )

    assert proposed.status_code == 403


async def test_the_database_refuses_self_activation_too(session: AsyncSession) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    session.add(PolicyConfig(kind="tiering", version=2, rules=_tiering(), created_by_id=ops.id))
    await session.commit()

    with pytest.raises(IntegrityError, match="ck_policy_configs_two_person"):
        await session.execute(
            update(PolicyConfig).where(PolicyConfig.version == 2).values(activated_by_id=ops.id)
        )

from datetime import timedelta
from typing import Any

import pytest
import redis.exceptions as redis_exceptions
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.identity.models import AccessGrant, RefreshSession, UserAccount
from app.modules.identity.sessions import SessionService
from tests.support import bearer, make_user, make_worker

SCIM = {"Authorization": "Bearer scim-test-token", "Content-Type": "application/scim+json"}
PATCH_SCHEMA = ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]


def _patch(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": PATCH_SCHEMA, "Operations": list(operations)}


async def _pm_with_session(session: AsyncSession, settings: Settings) -> UserAccount:
    user = await make_user(session, role=UserRole.PM, oidc_subject="kc-ama")
    await SessionService(session, settings).start(user, amr=["otp"])
    await session.commit()
    return user


async def test_deactivation_revokes_everything_immediately(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    redis: fake_aioredis.FakeRedis,
) -> None:
    user = await _pm_with_session(session, settings)
    live_token = bearer(settings, user)

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "active", "value": False}),
        headers=SCIM,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/scim+json")
    assert response.json()["active"] is False
    session.expire_all()
    # NOTE: session.get() on an object already in the identity map, after
    # expire_all(), triggers an implicit synchronous expired-attribute reload
    # that raises sqlalchemy.exc.MissingGreenlet under AsyncSession (SQLAlchemy
    # 2.0.35 + asyncpg 0.29.0 in this environment). session.refresh() performs
    # the same reload through the async-aware path.
    await session.refresh(user)
    assert user.status is AccountStatus.REVOKED
    sessions = (await session.scalars(select(RefreshSession))).all()
    assert all(s.revoked_at is not None for s in sessions)
    assert await redis.get(f"revoked_after:{user.id}") is not None
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "access.revoked"))
    ).one()
    assert audit.after == {"status": "revoked", "role": "pm"}
    event = (await session.scalars(select(OutboxEvent))).one()
    assert (event.event_type, event.payload["reason"]) == ("identity.access_revoked", "deactivated")
    me = await client.get("/api/v1/me", headers=live_token)
    assert me.json()["code"] == "session_revoked"


async def test_deactivation_closes_open_access_grants(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await _pm_with_session(session, settings)
    worker, _ = await make_worker(session)
    grant = AccessGrant(
        granted_to_id=user.id,
        scoped_worker_id=worker.id,
        reason="staffing review",
        expires_at=utcnow() + timedelta(days=30),
    )
    session.add(grant)
    await session.commit()

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "active", "value": False}),
        headers=SCIM,
    )

    assert response.status_code == 200
    session.expire_all()
    await session.refresh(grant)
    assert grant.revoked_at is not None
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "access_grant.revoked"))
    ).one()
    assert audit.target_id == grant.id
    assert audit.reason == "deactivated"


class _FailingRedis:
    """Stands in for app.state.redis: every command raises, like a Redis
    outage or network partition would."""

    async def set(self, *args: Any, **kwargs: Any) -> None:
        raise redis_exceptions.ConnectionError("redis down")


async def test_deactivation_survives_redis_being_down(
    client: AsyncClient,
    app: FastAPI,
    session: AsyncSession,
    settings: Settings,
) -> None:
    user = await _pm_with_session(session, settings)
    app.state.redis = _FailingRedis()

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "active", "value": False}),
        headers=SCIM,
    )

    assert response.status_code == 200
    session.expire_all()
    await session.refresh(user)
    assert user.status is AccountStatus.REVOKED
    sessions = (await session.scalars(select(RefreshSession))).all()
    assert sessions and all(s.revoked_at is not None for s in sessions)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "access.revoked"))
    ).one()
    assert audit.after == {"status": "revoked", "role": "pm"}


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "Replace", "path": "active", "value": "False"},  # Azure AD sends strings
        {"op": "replace", "value": {"active": False}},  # path-less form
    ],
)
async def test_other_deactivation_shapes_are_understood(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    operation: dict[str, Any],
) -> None:
    user = await _pm_with_session(session, settings)

    await client.patch("/api/v1/scim/v2/Users/kc-ama", json=_patch(operation), headers=SCIM)

    session.expire_all()
    await session.refresh(user)
    assert user.status is AccountStatus.REVOKED


async def test_role_change_revokes_sessions_and_updates_role(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await _pm_with_session(session, settings)

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "roles", "value": [{"value": "finance"}]}),
        headers=SCIM,
    )

    assert response.status_code == 200
    session.expire_all()
    await session.refresh(user)
    assert (user.role, user.status) == (UserRole.FINANCE, AccountStatus.ACTIVE)
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.payload["reason"] == "role_changed"


async def test_reactivation_restores_access_without_revoking(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, oidc_subject="kc-ama", status=AccountStatus.REVOKED)

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "active", "value": True}),
        headers=SCIM,
    )

    assert response.json()["active"] is True
    assert (await session.scalars(select(OutboxEvent))).all() == []
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions == ["user.reactivated"]


async def test_invalid_values_are_rejected(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, oidc_subject="kc-ama")

    bad_bool = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "active", "value": "maybe"}),
        headers=SCIM,
    )
    bad_role = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "roles", "value": [{"value": "overlord"}]}),
        headers=SCIM,
    )

    assert bad_bool.json()["code"] == "scim_invalid_value"
    assert bad_role.json()["code"] == "scim_invalid_value"


async def test_unknown_subject_is_404(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/scim/v2/Users/nobody",
        json=_patch({"op": "replace", "path": "active", "value": False}),
        headers=SCIM,
    )

    assert response.json()["code"] == "scim_user_not_found"


@pytest.mark.parametrize("auth", [None, "Bearer wrong-token"])
async def test_scim_requires_the_scim_token(client: AsyncClient, auth: str | None) -> None:
    headers = {"Content-Type": "application/scim+json"}
    if auth:
        headers["Authorization"] = auth

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "active", "value": False}),
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["code"] == "scim_unauthorized"


@pytest.mark.parametrize("path", ["active", "roles"])
async def test_removing_a_managed_attribute_is_rejected(
    client: AsyncClient, session: AsyncSession, path: str
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama", json=_patch({"op": "remove", "path": path}), headers=SCIM
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_unsupported_operation"


async def test_removing_an_unmanaged_attribute_is_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "remove", "path": "name.givenName"}),
        headers=SCIM,
    )

    assert response.status_code == 200
    await session.refresh(user)
    assert user.status is AccountStatus.ACTIVE


async def test_unknown_operation_is_rejected(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "copy", "path": "active", "value": False}),
        headers=SCIM,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_unsupported_operation"


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "remove", "path": 'roles[value eq "pm"]'},
        {"op": "remove", "value": {"roles": [{"value": "finance"}]}},
        {"op": "replace", "path": 'roles[value eq "pm"]', "value": [{"value": "finance"}]},
    ],
)
async def test_scim_paths_are_normalized_case_and_filter_insensitively(
    client: AsyncClient, session: AsyncSession, operation: dict[str, Any]
) -> None:
    """SCIM attribute names are case-insensitive (RFC 7643 §2.1); IdPs may also
    address a managed attribute with a value filter or via a path-less dict.
    All three shapes must be recognized as touching a managed attribute, not
    silently accepted as a no-op."""
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama", json=_patch(operation), headers=SCIM
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_unsupported_operation"


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "replace", "path": "Active", "value": False},
        {"op": "replace", "value": {"Active": False}},
    ],
)
async def test_scim_case_and_path_less_deactivation_takes_effect(
    client: AsyncClient, session: AsyncSession, operation: dict[str, Any]
) -> None:
    user = await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama", json=_patch(operation), headers=SCIM
    )

    assert response.status_code == 200
    session.expire_all()
    await session.refresh(user)
    assert user.status is AccountStatus.REVOKED


async def test_staff_account_cannot_be_given_the_worker_role(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "roles", "value": [{"value": "worker"}]}),
        headers=SCIM,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_invalid_value"


URN = "urn:ietf:params:scim:schemas:core:2.0:User:"


async def test_fully_qualified_active_path_deactivates(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await _pm_with_session(session, settings)

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": f"{URN}active", "value": False}),
        headers=SCIM,
    )

    assert response.status_code == 200
    await session.refresh(user)
    assert user.status is AccountStatus.REVOKED


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "remove", "path": f"{URN}roles"},
        {"op": "replace", "path": "urn:example:custom:2.0:User:active", "value": False},
    ],
)
async def test_urn_paths_to_managed_attributes_are_never_silently_ignored(
    client: AsyncClient, session: AsyncSession, operation: dict[str, object]
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama", json=_patch(operation), headers=SCIM
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_unsupported_operation"


async def test_enterprise_extension_attributes_are_still_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch(
            {
                "op": "replace",
                "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:manager",
                "value": {"value": "someone"},
            }
        ),
        headers=SCIM,
    )

    assert response.status_code == 200

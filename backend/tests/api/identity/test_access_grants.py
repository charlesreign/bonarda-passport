from datetime import timedelta
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.identity.grants import GrantService
from app.modules.identity.models import AccessGrant
from tests.support import bearer, make_user


def _body(granted_to: object, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "granted_to_id": str(granted_to),
        "scoped_worker_id": str(uuid4()),
        "reason": "Cross-team staffing for Project Volta",
        "expires_at": (utcnow() + timedelta(days=7)).isoformat(),
    }
    body.update(overrides)
    return body


async def test_people_ops_grants_pm_temporary_access(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/access-grants", json=_body(pm.id), headers=bearer(settings, ops)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["granted_to_id"] == str(pm.id)
    assert body["granted_by_id"] == str(ops.id)
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id, audit.reason) == (
        "access_grant.created",
        ops.id,
        "Cross-team staffing for Project Volta",
    )
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "identity.grant_created"


async def test_pm_cannot_create_grants(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/access-grants", json=_body(pm.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 403


async def test_grantee_must_be_an_active_pm(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    finance = await make_user(session, role=UserRole.FINANCE)

    response = await client.post(
        "/api/v1/access-grants", json=_body(finance.id), headers=bearer(settings, ops)
    )

    assert response.json()["code"] == "grant_invalid_grantee"


async def test_expiry_must_be_future_and_within_90_days(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, ops)

    past = await client.post(
        "/api/v1/access-grants",
        json=_body(pm.id, expires_at=(utcnow() - timedelta(hours=1)).isoformat()),
        headers=headers,
    )
    too_long = await client.post(
        "/api/v1/access-grants",
        json=_body(pm.id, expires_at=(utcnow() + timedelta(days=91)).isoformat()),
        headers=headers,
    )

    assert past.json()["code"] == "grant_expiry_in_past"
    assert too_long.json()["code"] == "grant_too_long"


async def test_naive_expiry_datetime_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/access-grants",
        json=_body(pm.id, expires_at="2026-10-01T00:00:00"),
        headers=bearer(settings, ops),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_reason_is_required(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/access-grants", json=_body(pm.id, reason="ok"), headers=bearer(settings, ops)
    )

    assert response.status_code == 422


async def test_list_and_revoke(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, ops)
    created = await client.post("/api/v1/access-grants", json=_body(pm.id), headers=headers)
    grant_id = created.json()["id"]

    listed = await client.get(
        "/api/v1/access-grants", params={"granted_to_id": str(pm.id)}, headers=headers
    )
    revoked = await client.delete(f"/api/v1/access-grants/{grant_id}", headers=headers)
    after = await client.get("/api/v1/access-grants", headers=headers)

    assert [g["id"] for g in listed.json()] == [grant_id]
    assert revoked.status_code == 204
    assert after.json() == []
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "access_grant.revoked" in actions


async def test_revoking_unknown_grant_is_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.delete(
        f"/api/v1/access-grants/{uuid4()}", headers=bearer(settings, ops)
    )

    assert response.json()["code"] == "grant_not_found"


async def test_sweep_records_lapsed_grants_once(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    lapsed_at = utcnow() - timedelta(minutes=3)
    session.add_all(
        [
            AccessGrant(
                granted_to_id=pm.id,
                scoped_worker_id=uuid4(),
                reason="old cover",
                expires_at=lapsed_at,
            ),
            AccessGrant(
                granted_to_id=pm.id,
                scoped_worker_id=uuid4(),
                reason="live cover",
                expires_at=utcnow() + timedelta(days=1),
            ),
        ]
    )
    await session.commit()

    first = await GrantService(session).sweep_expired()
    await session.commit()
    second = await GrantService(session).sweep_expired()

    assert (first, second) == (1, 0)
    expired = (
        await session.scalars(select(AccessGrant).where(AccessGrant.reason == "old cover"))
    ).one()
    assert expired.revoked_at == lapsed_at
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions == ["access_grant.expired"]

import asyncio
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow
from app.modules.identity.models import RefreshSession, UserAccount
from app.modules.identity.router import COOKIE_PATH, REFRESH_COOKIE
from app.modules.identity.sessions import IssuedSession, SessionService
from app.modules.identity.tokens import hash_token
from tests.support import make_user


async def _start(session: AsyncSession, settings: Settings, user: UserAccount) -> IssuedSession:
    issued = await SessionService(session, settings).start(user, amr=["email"])
    await session.commit()
    return issued


def _use_cookie(client: AsyncClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, token, domain="api.test", path=COOKIE_PATH)


async def test_refresh_rotates_token_and_returns_access_token(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.WORKER)
    issued = await _start(session, settings, user)
    _use_cookie(client, issued.refresh_token)

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 600
    new_cookie = response.cookies[REFRESH_COOKIE]
    assert new_cookie != issued.refresh_token
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["id"] == str(user.id)


async def test_concurrent_reuse_within_grace_is_retryable_not_theft(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session)
    issued = await _start(session, settings, user)
    _use_cookie(client, issued.refresh_token)
    first = await client.post("/api/v1/auth/refresh")
    winner = first.cookies[REFRESH_COOKIE]

    _use_cookie(client, issued.refresh_token)  # second tab still holds the old cookie
    second = await client.post("/api/v1/auth/refresh")

    assert second.status_code == 401
    assert second.json()["code"] == "refresh_superseded"
    _use_cookie(client, winner)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200


async def test_concurrent_rotation_is_serialized_by_row_lock(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession, settings: Settings
) -> None:
    """Two truly concurrent rotations of the same token must not both mint a
    child session: the row lock in `get_by_hash_for_update` forces the loser
    to see `revoked_at` already set once the winner commits."""
    user = await make_user(session)
    issued = await _start(session, settings, user)

    async def _rotate() -> IssuedSession | Unauthorized:
        async with sessionmaker() as s:
            try:
                result = await SessionService(s, settings).rotate(issued.refresh_token)
                await s.commit()
                return result
            except Unauthorized as exc:
                await s.rollback()
                return exc

    results = await asyncio.gather(_rotate(), _rotate())

    successes = [r for r in results if isinstance(r, IssuedSession)]
    failures = [r for r in results if isinstance(r, Unauthorized)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code == "refresh_superseded"

    remaining = (
        await session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)
            )
        )
    ).all()
    assert len(remaining) == 1


async def test_reuse_after_grace_revokes_the_whole_family(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session)
    issued = await _start(session, settings, user)
    _use_cookie(client, issued.refresh_token)
    rotated = (await client.post("/api/v1/auth/refresh")).cookies[REFRESH_COOKIE]
    await session.execute(
        update(RefreshSession)
        .where(RefreshSession.token_hash == hash_token(issued.refresh_token))
        .values(revoked_at=utcnow() - timedelta(minutes=5))
    )
    await session.commit()

    _use_cookie(client, issued.refresh_token)
    stolen = await client.post("/api/v1/auth/refresh")

    assert stolen.status_code == 401
    assert stolen.json()["code"] == "refresh_reuse_detected"
    _use_cookie(client, rotated)  # the legitimate holder's token died with the family
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    audit = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.refresh_reuse_detected" in audit


async def test_expired_session_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session)
    issued = await _start(session, settings, user)
    await session.execute(update(RefreshSession).values(expires_at=utcnow() - timedelta(seconds=1)))
    await session.commit()
    _use_cookie(client, issued.refresh_token)

    response = await client.post("/api/v1/auth/refresh")

    assert response.json()["code"] == "session_expired"


async def test_staff_session_never_extends_past_absolute_maximum(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)
    issued = await _start(session, settings, user)
    started = utcnow() - timedelta(hours=11, minutes=50)
    await session.execute(update(RefreshSession).values(family_started_at=started))
    await session.commit()

    await SessionService(session, settings).rotate(issued.refresh_token)
    await session.commit()

    newest = (
        await session.scalars(select(RefreshSession).where(RefreshSession.revoked_at.is_(None)))
    ).one()
    assert newest.expires_at <= started + timedelta(seconds=settings.staff_session_max_seconds)


async def test_deactivated_account_cannot_refresh(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session)
    issued = await _start(session, settings, user)
    user.status = AccountStatus.REVOKED
    await session.commit()
    _use_cookie(client, issued.refresh_token)

    response = await client.post("/api/v1/auth/refresh")

    assert response.json()["code"] == "account_inactive"


async def test_missing_cookie_is_401(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_refresh"


async def test_logout_revokes_family_and_clears_cookie(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session)
    issued = await _start(session, settings, user)
    _use_cookie(client, issued.refresh_token)

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert 'bonarda_refresh=""' in response.headers["set-cookie"]
    _use_cookie(client, issued.refresh_token)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    audit = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.logout" in audit


async def test_logged_out_token_presented_again_is_session_revoked_not_theft(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    """Logout sets revoked_at on every session in the family, same as
    rotation does. Presenting that same token afterwards (e.g. a second tab
    that never saw the logout) must be read as an ended session, not as
    stolen-token reuse."""
    user = await make_user(session)
    issued = await _start(session, settings, user)
    _use_cookie(client, issued.refresh_token)
    logout_response = await client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 204

    _use_cookie(client, issued.refresh_token)
    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["code"] == "session_revoked"
    audit = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.refresh_reuse_detected" not in audit


async def test_admin_revoked_token_presented_again_is_session_revoked_not_theft(
    session: AsyncSession, settings: Settings
) -> None:
    """Same as logout: an admin/SCIM-driven revoke_all_for_user must not be
    misread as token theft on the next refresh attempt."""
    user = await make_user(session)
    issued = await _start(session, settings, user)
    service = SessionService(session, settings)
    await service.refresh.revoke_all_for_user(user.id, utcnow(), reason="admin")
    await session.commit()

    with pytest.raises(Unauthorized) as excinfo:
        await service.rotate(issued.refresh_token)

    assert excinfo.value.code == "session_revoked"
    audit = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.refresh_reuse_detected" not in audit


async def test_me_returns_the_account(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PEOPLE_OPS, email="ama@bonarda.works")
    issued = await _start(session, settings, user)

    response = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {issued.access_token}"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": "ama@bonarda.works",
        "role": "people_ops",
        "worker_id": None,
        "can_view_governance": False,
        "locale": "en",
    }

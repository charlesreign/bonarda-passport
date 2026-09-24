from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.time import utcnow
from app.modules.engagements.models import ProjectStaff
from app.modules.identity.models import AccessGrant, RefreshSession, UserAccount
from app.modules.identity.oidc import IdTokenClaims
from app.modules.identity.oidc_login import OidcLoginService
from app.modules.identity.router import OIDC_STATE_COOKIE, REFRESH_COOKIE
from app.modules.identity.sessions import SessionService
from tests.support import bearer, make_project, make_user, make_worker


@dataclass
class FakeOidcProvider:
    claims: IdTokenClaims = field(
        default_factory=lambda: IdTokenClaims(
            subject="kc-ama",
            email="Ama@Bonarda.works",
            amr=["pwd", "otp"],
            acr=None,
            groups=["bonarda-pm"],
        )
    )
    exchanges: list[dict[str, str]] = field(default_factory=list)

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        return f"https://idp.test/auth?state={state}&nonce={nonce}"

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> IdTokenClaims:
        self.exchanges.append({"code": code, "code_verifier": code_verifier, "nonce": nonce})
        return self.claims


@pytest.fixture
def idp(app: FastAPI) -> FakeOidcProvider:
    fake = FakeOidcProvider()
    app.state.oidc_provider = fake
    return fake


async def _login(client: AsyncClient) -> str:
    response = await client.get("/api/v1/auth/oidc/login")
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


async def test_first_login_provisions_staff_account(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    state = await _login(client)

    response = await client.get(
        "/api/v1/auth/oidc/callback", params={"code": "c0de", "state": state}
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://app.test/console"
    assert REFRESH_COOKIE in response.cookies
    set_cookie_headers = response.headers.get_list("set-cookie")
    state_cookie_header = next(
        h for h in set_cookie_headers if h.startswith(f"{OIDC_STATE_COOKIE}=")
    )
    assert (
        state_cookie_header.startswith(f"{OIDC_STATE_COOKIE}=;")
        or "Max-Age=0" in state_cookie_header
    )
    user = (await session.scalars(select(UserAccount))).one()
    assert (user.email, user.role, user.auth_provider) == (
        "ama@bonarda.works",
        UserRole.PM,
        AuthProvider.CORPORATE_SSO,
    )
    assert idp.exchanges[0]["code"] == "c0de"
    assert len(idp.exchanges[0]["code_verifier"]) >= 43
    actions = set((await session.scalars(select(AuditLog.action))).all())
    assert {"user.provisioned", "auth.sso_login"} <= actions


async def test_login_without_mfa_is_refused(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    idp.claims = IdTokenClaims(
        subject="kc-ama", email="ama@bonarda.works", amr=["pwd"], acr=None, groups=["bonarda-pm"]
    )
    state = await _login(client)

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.status_code == 403
    assert response.json()["code"] == "mfa_required"
    assert (await session.scalars(select(UserAccount))).all() == []


async def test_accepted_acr_satisfies_mfa(
    app: FastAPI, client: AsyncClient, idp: FakeOidcProvider
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"oidc_accepted_acr": ["gold"]})
    idp.claims = IdTokenClaims(
        subject="kc-ama", email="ama@bonarda.works", amr=[], acr="gold", groups=["bonarda-pm"]
    )
    state = await _login(client)

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.status_code == 302


async def test_login_without_mapped_group_is_refused(
    client: AsyncClient, idp: FakeOidcProvider
) -> None:
    idp.claims = IdTokenClaims(
        subject="kc-x", email="x@bonarda.works", amr=["otp"], acr=None, groups=["marketing"]
    )
    state = await _login(client)

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.json()["code"] == "no_role_assigned"


async def test_highest_privilege_group_wins(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    idp.claims = IdTokenClaims(
        subject="kc-ama",
        email="ama@bonarda.works",
        amr=["otp"],
        acr=None,
        groups=["bonarda-pm", "bonarda-people-ops"],
    )
    state = await _login(client)

    await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    user = (await session.scalars(select(UserAccount))).one()
    assert user.role is UserRole.PEOPLE_OPS


async def test_changed_group_updates_role_and_is_audited(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    await make_user(session, role=UserRole.PM, email="ama@bonarda.works", oidc_subject="kc-ama")
    idp.claims = IdTokenClaims(
        subject="kc-ama",
        email="ama@bonarda.works",
        amr=["otp"],
        acr=None,
        groups=["bonarda-finance"],
    )
    state = await _login(client)

    await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    session.expire_all()
    user = (await session.scalars(select(UserAccount))).one()
    assert user.role is UserRole.FINANCE
    change = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "user.role_changed"))
    ).one()
    assert (change.before, change.after) == ({"role": "pm"}, {"role": "finance"})


async def test_role_change_at_login_ends_the_pms_staffing(
    client: AsyncClient,
    session: AsyncSession,
    idp: FakeOidcProvider,
    drain: Callable[[], Awaitable[None]],
) -> None:
    ama = await make_user(
        session, role=UserRole.PM, email="ama@bonarda.works", oidc_subject="kc-ama"
    )
    project = await make_project(session, staff=[ama])
    idp.claims = IdTokenClaims(
        subject="kc-ama",
        email="ama@bonarda.works",
        amr=["otp"],
        acr=None,
        groups=["bonarda-finance"],
    )
    state = await _login(client)

    await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    await drain()

    staff = (
        await session.scalars(
            select(ProjectStaff).where(
                ProjectStaff.project_id == project.id, ProjectStaff.active_to.is_(None)
            )
        )
    ).all()
    assert staff == []
    removed = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "project.staff_removed"))
    ).one()
    assert removed.reason == "role_changed"


async def test_deactivated_account_cannot_sign_in(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    await make_user(
        session, email="ama@bonarda.works", oidc_subject="kc-ama", status=AccountStatus.REVOKED
    )
    state = await _login(client)

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.json()["code"] == "account_inactive"


async def test_email_owned_by_another_account_is_a_conflict(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    await make_user(session, role=UserRole.WORKER, email="ama@bonarda.works")
    state = await _login(client)

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.status_code == 409
    assert response.json()["code"] == "email_conflict"


async def test_state_can_only_be_used_once(client: AsyncClient, idp: FakeOidcProvider) -> None:
    state = await _login(client)
    await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    # The first (successful) callback clears the browser's state cookie, so a
    # bare replay would now fail the browser-binding check instead of
    # exercising the single-use Redis lookup. Re-present the cookie explicitly
    # to isolate what this test targets: state can't be redeemed twice.
    client.cookies.set(OIDC_STATE_COOKIE, state)
    replay = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert replay.status_code == 400
    assert replay.json()["code"] == "oidc_state_invalid"


async def test_idp_error_is_reported(client: AsyncClient, idp: FakeOidcProvider) -> None:
    response = await client.get(
        "/api/v1/auth/oidc/callback", params={"error": "access_denied", "state": "s"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "oidc_error"


async def test_login_sets_state_cookie(client: AsyncClient, idp: FakeOidcProvider) -> None:
    response = await client.get("/api/v1/auth/oidc/login")

    assert response.status_code == 302
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert response.cookies[OIDC_STATE_COOKIE] == state


async def test_callback_from_another_browser_is_rejected(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    state = await _login(client)
    client.cookies.clear()

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.status_code == 400
    assert response.json()["code"] == "oidc_state_mismatch"
    assert (await session.scalars(select(UserAccount))).all() == []


async def test_role_change_at_login_revokes_other_sessions(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider, settings: Settings
) -> None:
    user = await make_user(
        session, role=UserRole.PM, email="ama@bonarda.works", oidc_subject="kc-ama"
    )
    await SessionService(session, settings).start(user, amr=["otp"])
    await session.commit()
    old_token = bearer(settings, user, now=utcnow() - timedelta(seconds=5))
    idp.claims = IdTokenClaims(
        subject="kc-ama",
        email="ama@bonarda.works",
        amr=["otp"],
        acr=None,
        groups=["bonarda-finance"],
    )
    state = await _login(client)

    response = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert response.status_code == 302
    sessions = (
        await session.scalars(select(RefreshSession).where(RefreshSession.user_id == user.id))
    ).all()
    revoked = [s for s in sessions if s.revoked_at is not None]
    assert [s.revoked_reason for s in revoked] == ["admin"]
    assert len(sessions) == 2  # the old one (revoked) and the one this login issued
    stale = await client.get("/api/v1/me", headers=old_token)
    assert stale.json()["code"] == "session_revoked"


async def test_role_change_at_login_keeps_its_own_new_session_usable(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    """Guards the `marker_at = now - 1s` logic in `oidc_login.py`: the
    revocation marker must precede the session this same login issues, or
    the login would revoke itself."""
    await make_user(session, role=UserRole.PM, email="ama@bonarda.works", oidc_subject="kc-ama")
    idp.claims = IdTokenClaims(
        subject="kc-ama",
        email="ama@bonarda.works",
        amr=["otp"],
        acr=None,
        groups=["bonarda-finance"],
    )
    state = await _login(client)

    callback = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
    assert callback.status_code == 302

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    token = refreshed.json()["access_token"]

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["role"] == "finance"


async def test_completing_sign_in_writes_the_audit_row(
    session: AsyncSession, redis: fake_aioredis.FakeRedis, settings: Settings
) -> None:
    service = OidcLoginService(session, redis, settings, FakeOidcProvider())
    _, state = await service.begin()

    user, _ = await service.complete(code="c0de", state=state)
    await session.commit()

    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "auth.sso_login"))
    ).one()
    assert (audit.actor_id, audit.after) == (user.id, {"amr": ["pwd", "otp"]})


async def test_role_change_at_login_closes_the_pms_grants(
    client: AsyncClient, session: AsyncSession, idp: FakeOidcProvider
) -> None:
    ama = await make_user(
        session, role=UserRole.PM, email="ama@bonarda.works", oidc_subject="kc-ama"
    )
    worker, _ = await make_worker(session)
    grant = AccessGrant(
        granted_to_id=ama.id,
        scoped_worker_id=worker.id,
        reason="Covering for a colleague on leave",
        expires_at=utcnow() + timedelta(days=5),
    )
    session.add(grant)
    await session.commit()
    idp.claims = IdTokenClaims(
        subject="kc-ama",
        email="ama@bonarda.works",
        amr=["otp"],
        acr=None,
        groups=["bonarda-finance"],
    )
    state = await _login(client)

    await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    await session.refresh(grant)
    assert grant.revoked_at is not None
    revoked = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "access.revoked"))
    ).one()
    assert (revoked.reason, revoked.before, revoked.after) == (
        "role_changed",
        {"status": "active", "role": "pm"},
        {"status": "active", "role": "finance"},
    )

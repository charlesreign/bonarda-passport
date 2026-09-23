from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import OnboardingState
from app.modules.passport.models import Worker
from tests.support import RecordingMailer, bearer, make_user

Drain = Callable[[], Awaitable[None]]
URL = "/api/v1/workers/invitations"
BODY = {
    "email": "Grace@Example.com",
    "full_name": "Grace Owusu",
    "worker_type": "freelancer",
    "data_region": "GH",
    "locale": "fr",
}


async def test_pm_invites_a_first_time_worker(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    mailer: RecordingMailer,
    drain: Drain,
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=BODY, headers=bearer(settings, pm))
    await drain()

    assert response.status_code == 201
    body = response.json()
    assert (body["email"], body["onboarding_state"]) == ("grace@example.com", "invited")
    worker = (await session.scalars(select(Worker))).one()
    assert (worker.full_name, worker.onboarding_state) == ("Grace Owusu", OnboardingState.INVITED)
    account = (
        await session.scalars(select(UserAccount).where(UserAccount.worker_id == worker.id))
    ).one()
    assert (account.role, account.locale) == (UserRole.WORKER, "fr")
    actions = set((await session.scalars(select(AuditLog.action))).all())
    assert {"worker.invited", "user.provisioned"} <= actions
    assert [m["to"] for m in mailer.sent] == ["grace@example.com"]
    assert mailer.sent[0]["subject"] == "Vous êtes invité(e) sur Bonarda Works"


async def test_invited_worker_signs_in_and_sees_their_passport(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    mailer: RecordingMailer,
    drain: Drain,
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await client.post(URL, json=BODY, headers=bearer(settings, pm))
    await drain()

    signed_in = await client.post("/api/v1/auth/magic-link/verify", json={"token": mailer.token()})
    token = signed_in.json()["access_token"]
    passport = await client.get("/api/v1/workers/me", headers={"Authorization": f"Bearer {token}"})

    assert passport.json()["onboarding_state"] == "invited"
    assert passport.json()["full_name"] == "Grace Owusu"


async def test_existing_email_is_a_conflict_and_leaves_no_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM, email="grace@example.com")

    response = await client.post(URL, json=BODY, headers=bearer(settings, pm))

    assert response.status_code == 409
    assert response.json()["code"] == "email_in_use"
    assert (await session.scalars(select(Worker))).all() == []


@pytest.mark.parametrize("role", [UserRole.PEOPLE_OPS, UserRole.WORKER, UserRole.FINANCE])
async def test_only_pms_invite(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    user = await make_user(session, role=role)

    response = await client.post(URL, json=BODY, headers=bearer(settings, user))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "override",
    [{"data_region": "ghana"}, {"email": "not-an-email"}, {"full_name": ""}, {"locale": "de"}],
)
async def test_invalid_invitations_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, override: dict[str, str]
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=BODY | override, headers=bearer(settings, pm))

    assert response.status_code == 422

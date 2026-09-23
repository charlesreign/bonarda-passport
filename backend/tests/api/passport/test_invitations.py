import json
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import OnboardingState
from app.modules.passport.models import Worker
from tests.support import RecordingMailer, bearer, make_user, make_worker

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
    assert (body["email"], body["onboarding_state"], body["resent"]) == (
        "grace@example.com",
        "invited",
        False,
    )
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
    # Erasure (spec §6.3): audit rows about a worker carry no contact data —
    # they are append-only and kept 7 years, past any erasure request.
    audit_rows = (await session.scalars(select(AuditLog))).all()
    for row in audit_rows:
        assert "grace@example.com" not in json.dumps(row.before)
        assert "grace@example.com" not in json.dumps(row.after)


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


async def test_reinviting_a_worker_still_invited_resends(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    mailer: RecordingMailer,
    drain: Drain,
) -> None:
    """A lost invitation email (SMTP outage exhausting handler retries, dead-
    lettered) must not strand a worker at `invited` forever: re-inviting the
    same email resends instead of 409-ing."""
    pm = await make_user(session, role=UserRole.PM)

    first = await client.post(URL, json=BODY, headers=bearer(settings, pm))
    await drain()
    second = await client.post(URL, json=BODY, headers=bearer(settings, pm))
    await drain()

    assert first.status_code == 201
    assert second.status_code == 200
    body = second.json()
    assert (body["email"], body["onboarding_state"], body["resent"]) == (
        "grace@example.com",
        "invited",
        True,
    )
    workers = (await session.scalars(select(Worker))).all()
    assert len(workers) == 1
    assert body["worker_id"] == str(workers[0].id)
    assert [m["to"] for m in mailer.sent] == ["grace@example.com", "grace@example.com"]
    actions = list((await session.scalars(select(AuditLog.action))).all())
    assert actions.count("worker.invitation_resent") == 1
    resent_audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "worker.invitation_resent"))
    ).one()
    assert "grace@example.com" not in json.dumps(resent_audit.after)


async def test_reinviting_a_worker_past_invited_is_still_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_worker(
        session, email="grace@example.com", onboarding_state=OnboardingState.PROFILE_COMPLETE
    )

    response = await client.post(URL, json=BODY, headers=bearer(settings, pm))

    assert response.status_code == 409
    assert response.json()["code"] == "email_in_use"
    assert len((await session.scalars(select(Worker))).all()) == 1


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


async def test_resend_updates_the_invited_workers_details(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    mailer: RecordingMailer,
    drain: Drain,
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, pm)
    await client.post(URL, json=BODY, headers=headers)

    response = await client.post(
        URL, json=BODY | {"full_name": "Grace A. Owusu", "data_region": "EU"}, headers=headers
    )

    assert response.status_code == 200
    worker = (await session.scalars(select(Worker))).one()
    await session.refresh(worker)
    assert (worker.full_name, worker.data_region) == ("Grace A. Owusu", "EU")
    resent = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "worker.invitation_resent"))
    ).one()
    assert resent.before == {
        "full_name": "Grace Owusu",
        "data_region": "GH",
        "worker_type": "freelancer",
    }
    assert resent.after == {
        "full_name": "Grace A. Owusu",
        "data_region": "EU",
        "worker_type": "freelancer",
    }


async def test_resends_are_limited_per_hour(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, pm)
    await client.post(URL, json=BODY, headers=headers)
    statuses = [(await client.post(URL, json=BODY, headers=headers)).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


async def test_revoked_invited_account_is_not_resent(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, pm)
    await client.post(URL, json=BODY, headers=headers)
    account = (
        await session.scalars(select(UserAccount).where(UserAccount.role == UserRole.WORKER))
    ).one()
    account.status = AccountStatus.REVOKED
    await session.commit()

    response = await client.post(URL, json=BODY, headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "email_in_use"


async def test_openapi_documents_the_resend_response(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()

    responses = spec["paths"]["/api/v1/workers/invitations"]["post"]["responses"]
    assert {"200", "201"} <= set(responses)


async def test_invitation_region_must_be_configured(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        URL, json=BODY | {"data_region": "ZZ"}, headers=bearer(settings, pm)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_data_region"
    assert (await session.scalars(select(Worker))).all() == []

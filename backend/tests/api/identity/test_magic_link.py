from collections.abc import Awaitable, Callable

from fakeredis import aioredis as fake_aioredis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.enums import AccountStatus, UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.identity.router import REFRESH_COOKIE
from tests.support import RecordingMailer, make_user

Drain = Callable[[], Awaitable[None]]


async def test_request_queues_the_link_instead_of_mailing_inline(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    worker = await make_user(session, role=UserRole.WORKER, email="kofi@example.com")

    response = await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})

    assert response.status_code == 202
    assert mailer.sent == []
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "identity.magic_link_requested"
    assert event.payload == {"aggregate_id": str(worker.id), "purpose": "sign_in"}


async def test_known_worker_receives_single_use_link(
    client: AsyncClient,
    session: AsyncSession,
    mailer: RecordingMailer,
    drain: Drain,
    redis: fake_aioredis.FakeRedis,
) -> None:
    await make_user(session, role=UserRole.WORKER, email="kofi@example.com")

    await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})
    await drain()

    assert [m["to"] for m in mailer.sent] == ["kofi@example.com"]
    assert mailer.sent[0]["subject"] == "Your Bonarda sign-in link"
    assert "http://app.test/auth/verify#token=" in mailer.sent[0]["body"]
    assert mailer.token() not in str(await redis.keys("*"))  # only the hash is stored


async def test_link_is_written_in_the_account_locale(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    worker = await make_user(session, role=UserRole.WORKER, email="awa@example.com")
    worker.locale = "fr"
    await session.commit()

    await client.post("/api/v1/auth/magic-link", json={"email": "awa@example.com"})
    await drain()

    assert mailer.sent[0]["subject"] == "Votre lien de connexion Bonarda"


async def test_worker_deactivated_before_sending_gets_no_link(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    worker = await make_user(session, role=UserRole.WORKER, email="kofi@example.com")
    await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})
    worker.status = AccountStatus.REVOKED
    await session.commit()

    await drain()

    assert mailer.sent == []


async def test_email_matching_ignores_case_and_whitespace(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    await make_user(session, role=UserRole.WORKER, email="kofi@example.com")

    await client.post("/api/v1/auth/magic-link", json={"email": " Kofi@Example.com "})
    await drain()

    assert [m["to"] for m in mailer.sent] == ["kofi@example.com"]


async def test_unknown_email_gets_same_response_and_no_mail(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    response = await client.post("/api/v1/auth/magic-link", json={"email": "nobody@example.com"})
    await drain()

    assert response.status_code == 202
    assert mailer.sent == []
    assert (await session.scalars(select(OutboxEvent))).all() == []


async def test_staff_accounts_cannot_use_magic_links(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    await make_user(session, role=UserRole.PM, email="ama@bonarda.works")

    response = await client.post("/api/v1/auth/magic-link", json={"email": "ama@bonarda.works"})
    await drain()

    assert response.status_code == 202
    assert mailer.sent == []


async def test_requests_are_rate_limited_per_email(client: AsyncClient) -> None:
    for _ in range(5):
        await client.post("/api/v1/auth/magic-link", json={"email": "grace@example.com"})

    response = await client.post("/api/v1/auth/magic-link", json={"email": "grace@example.com"})

    assert response.status_code == 429
    assert response.json()["code"] == "magic_link_rate_limited"


async def test_verify_starts_session_once(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    worker = await make_user(session, role=UserRole.WORKER, email="kofi@example.com")
    await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})
    await drain()
    token = mailer.token()

    first = await client.post("/api/v1/auth/magic-link/verify", json={"token": token})
    second = await client.post("/api/v1/auth/magic-link/verify", json={"token": token})

    assert first.status_code == 200
    assert first.json()["access_token"]
    assert REFRESH_COOKIE in first.cookies
    assert second.status_code == 401
    assert second.json()["code"] == "magic_link_invalid"
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.magic_link_login" in actions
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"}
    )
    assert me.json()["worker_id"] == str(worker.worker_id)


async def test_verify_rejects_unknown_token(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/magic-link/verify", json={"token": "forged"})

    assert response.status_code == 401
    assert response.json()["code"] == "magic_link_invalid"

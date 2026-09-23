import re
from dataclasses import dataclass, field

import pytest
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.enums import UserRole
from app.modules.identity.router import REFRESH_COOKIE
from tests.support import make_user


@dataclass
class RecordingMailer:
    sent: list[dict[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})

    def token(self) -> str:
        match = re.search(r"token=([A-Za-z0-9_-]+)", self.sent[-1]["body"])
        assert match is not None
        return match.group(1)


@pytest.fixture
def mailer(app: FastAPI) -> RecordingMailer:
    recording = RecordingMailer()
    app.state.mailer = recording
    return recording


async def test_known_worker_receives_single_use_link(
    client: AsyncClient,
    session: AsyncSession,
    mailer: RecordingMailer,
    redis: fake_aioredis.FakeRedis,
) -> None:
    await make_user(session, role=UserRole.WORKER, email="kofi@example.com")

    response = await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})

    assert response.status_code == 202
    assert [m["to"] for m in mailer.sent] == ["kofi@example.com"]
    assert "http://app.test/auth/verify#token=" in mailer.sent[0]["body"]
    assert mailer.token() not in str(await redis.keys("*"))  # only the hash is stored


async def test_email_matching_ignores_case_and_whitespace(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    await make_user(session, role=UserRole.WORKER, email="kofi@example.com")

    await client.post("/api/v1/auth/magic-link", json={"email": " Kofi@Example.com "})

    assert [m["to"] for m in mailer.sent] == ["kofi@example.com"]


async def test_unknown_email_gets_same_response_and_no_mail(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    response = await client.post("/api/v1/auth/magic-link", json={"email": "nobody@example.com"})

    assert response.status_code == 202
    assert mailer.sent == []


async def test_staff_accounts_cannot_use_magic_links(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    await make_user(session, role=UserRole.PM, email="ama@bonarda.works")

    response = await client.post("/api/v1/auth/magic-link", json={"email": "ama@bonarda.works"})

    assert response.status_code == 202
    assert mailer.sent == []


async def test_requests_are_rate_limited_per_email(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    for _ in range(5):
        await client.post("/api/v1/auth/magic-link", json={"email": "grace@example.com"})

    response = await client.post("/api/v1/auth/magic-link", json={"email": "grace@example.com"})

    assert response.status_code == 429
    assert response.json()["code"] == "magic_link_rate_limited"


async def test_verify_starts_session_once(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    worker = await make_user(session, role=UserRole.WORKER, email="kofi@example.com")
    await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})
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

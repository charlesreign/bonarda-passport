from datetime import timedelta

import pytest
from fakeredis import aioredis as fake_aioredis
from fastapi import APIRouter, FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.identity.dependencies import CurrentActor
from app.modules.identity.revocation import mark_revoked
from tests.support import bearer, make_user


@pytest.fixture
def whoami_route(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/_test/whoami")
    async def whoami(actor: CurrentActor) -> dict[str, str]:
        return {"user_id": str(actor.user_id), "role": actor.role.value}

    app.include_router(router)


pytestmark = pytest.mark.usefixtures("whoami_route")


async def test_valid_token_resolves_actor(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get("/_test/whoami", headers=bearer(settings, user))

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.id), "role": "people_ops"}


async def test_missing_token_is_401_problem(client: AsyncClient) -> None:
    response = await client.get("/_test/whoami")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_token"


async def test_token_issued_before_revocation_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    redis: fake_aioredis.FakeRedis,
) -> None:
    user = await make_user(session)
    headers = bearer(settings, user, now=utcnow() - timedelta(seconds=30))
    await mark_revoked(redis, settings, user.id, utcnow())

    response = await client.get("/_test/whoami", headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "session_revoked"


async def test_token_issued_after_revocation_is_accepted(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    redis: fake_aioredis.FakeRedis,
) -> None:
    user = await make_user(session)
    await mark_revoked(redis, settings, user.id, utcnow() - timedelta(seconds=60))

    response = await client.get("/_test/whoami", headers=bearer(settings, user))

    assert response.status_code == 200


class _DownRedis:
    async def get(self, key: str) -> str | None:
        raise RedisConnectionError("redis unavailable")


async def test_revocation_check_fails_open_when_redis_is_down(
    app: FastAPI, client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session)
    app.state.redis = _DownRedis()

    response = await client.get("/_test/whoami", headers=bearer(settings, user))

    assert response.status_code == 200

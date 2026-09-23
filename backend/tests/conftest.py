from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import pytest
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

import app.models_registry
from alembic import command
from app.core.config import Settings
from app.core.db.base import Base
from app.core.enums import UserRole
from app.main import create_app
from app.wiring import HandlerDeps, build_registry
from tests.support import RecordingMailer, alembic_config, drain_outbox


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    url: str = postgres.get_connection_url()
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        database_url="postgresql+asyncpg://unused:unused@localhost:1/unused",
        redis_url="redis://unused:1/0",
        public_app_url="http://app.test",
        jwt_signing_key=SecretStr("test-signing-key-that-is-at-least-32-bytes"),
        cookie_secure=False,
        oidc_issuer_url="https://idp.test/realms/bonarda",
        oidc_client_id="bonarda-api",
        oidc_client_secret=SecretStr("oidc-secret"),
        oidc_redirect_url="http://api.test/api/v1/auth/oidc/callback",
        oidc_group_role_map={
            "bonarda-pm": UserRole.PM,
            "bonarda-people-ops": UserRole.PEOPLE_OPS,
            "bonarda-finance": UserRole.FINANCE,
            "bonarda-admin": UserRole.ADMIN,
        },
        scim_bearer_token=SecretStr("scim-test-token"),
    )


@pytest.fixture
async def db_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def sessionmaker(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as s:
        yield s


@pytest.fixture
def redis() -> fake_aioredis.FakeRedis:
    return fake_aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def app(
    settings: Settings, database_url: str, db_engine: AsyncEngine, redis: fake_aioredis.FakeRedis
) -> FastAPI:
    return create_app(
        settings.model_copy(update={"database_url": database_url}), engine=db_engine, redis=redis
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api.test") as c:
        yield c


@pytest.fixture
def mailer(app: FastAPI) -> RecordingMailer:
    recording = RecordingMailer()
    app.state.mailer = recording
    return recording


@pytest.fixture
def drain(
    app: FastAPI,
    sessionmaker: async_sessionmaker[AsyncSession],
    mailer: RecordingMailer,
) -> Callable[[], Awaitable[None]]:
    registry = build_registry(
        HandlerDeps(settings=app.state.settings, redis=app.state.redis, mailer=mailer)
    )

    async def _drain() -> None:
        await drain_outbox(sessionmaker, registry)

    return _drain

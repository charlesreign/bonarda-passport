# Bonarda Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running FastAPI backend with the shared kernel (settings, DB, problem+json errors, correlation IDs, append-only audit log, transactional outbox with relay and idempotent handlers, Arq worker) and the complete `identity` module (tokens, refresh rotation, magic links, staff OIDC with MFA enforcement, permissions, visibility policy, access grants, SCIM revocation).

**Architecture:** Modular monolith (spec §4–5). `app/core` is the shared kernel; `app/modules/identity` is the first domain module and exposes its public API through `service.py` and `schemas.py` only. Every state change writes its audit row and outbox event on the request's `AsyncSession`, so they commit together. The Arq worker runs the outbox relay and event handlers. `app/main.py`, `app/worker/` and `app/wiring.py` are the composition root and may import any module.

**Tech Stack:** Python 3.12, FastAPI 0.115, Pydantic v2 + pydantic-settings, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis 7 (redis-py 5), Arq, PyJWT, authlib, structlog, pytest + pytest-asyncio + Testcontainers (Postgres 16) + fakeredis, ruff, mypy, import-linter.

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md` (roadmap: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`)

## Global Constraints

- Python **3.12+**. On this machine use `py -3.12` to create the venv. All commands below run from `backend/` with the venv activated (`source .venv/Scripts/activate` in Git Bash, `.venv\Scripts\activate` in PowerShell).
- Docker must be running: integration and API tests start `postgres:16-alpine` via Testcontainers.
- All routes are under `/api/v1` except `/health`. Errors are RFC 9457 `application/problem+json` with a stable `code` field.
- Access token TTL **600 s**. Staff refresh sessions: **30 min** idle, **12 h** absolute. Worker refresh sessions: **24 h** idle, **30 days** absolute. Revocation marker TTL **900 s** (NFR-3.5: revocation ≤ 15 min).
- Magic links: single-use, **15 min** TTL, stored only as SHA-256 hashes, rate-limited **5/hour per email** and **20/hour per IP**.
- Every state-changing service method calls `write_audit(...)` and (where the spec names an event) `emit_event(...)` on the **same** `AsyncSession`. Request code never enqueues Arq jobs directly.
- A module imports another module only through its `service` or `schemas` submodule. `app.core` never imports `app.modules`, `app.main`, `app.worker` or `app.wiring`.
- Enum columns store the enum **values** (lowercase strings) via `app.core.db.types.pg_enum`.
- All datetimes are timezone-aware UTC (`app.core.time.utcnow()`); request bodies use `AwareDatetime`.
- User-facing email text comes from `app.core.i18n` (English and French), never inline literals.
- Before every commit run: `ruff format . && ruff check . && mypy && lint-imports && pytest`. All must pass.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Two browser tabs refreshing at the same moment** send the same refresh token twice. The second must get a retryable `401 refresh_superseded`, not trigger theft detection that logs the user out everywhere. (Test in Task 6.)
2. **Email case and whitespace** — `" Kofi@Example.com "` requesting a magic link must match the stored `kofi@example.com`. (Test in Task 7.)
3. **Timezone-naive datetimes** in an access-grant request (`"2026-10-01T00:00:00"`) must be rejected with `422`, never crash comparing naive and aware datetimes. (Test in Task 10.)
4. **SCIM boolean strings** — Azure AD sends `"value": "False"`; `bool("False")` is `True`, so a naive parse would *keep* a departed employee active. Must deactivate. (Test in Task 11.)
5. **Hostile `X-Correlation-ID` headers** (overlong, spaces, punctuation) must be replaced with a generated ID, never echoed into logs or responses. (Test in Task 2.)

---

## File Structure

```
.gitignore                                   # repo-level ignores (Task 1)
.github/workflows/ci.yml                     # backend CI (Task 12)
docs/permissions.md                          # generated role matrix (Task 9)
backend/
  requirements.txt, requirements-dev.txt     # moved from repo root (Task 1)
  pyproject.toml                             # ruff, mypy, pytest, import-linter
  alembic.ini, alembic/env.py, alembic/script.py.mako
  alembic/versions/0001_core.py              # audit_log, outbox_events, processed_events, append-only trigger
  alembic/versions/0002_identity.py          # user_accounts, refresh_sessions, access_grants
  .env.example
  app/
    main.py                                  # create_app() factory — composition root
    wiring.py                                # event handler registry + visibility sources — composition root
    models_registry.py                       # imports every ORM model for Alembic/tests
    core/
      config.py        Settings
      enums.py         UserRole, AuthProvider, AccountStatus
      time.py          utcnow()
      context.py       correlation-ID context, Actor
      errors.py        AppError hierarchy + problem+json handlers
      logging.py       structlog configuration
      middleware.py    CorrelationIdMiddleware
      deps.py          SettingsDep, RedisDep
      health.py        GET /health
      i18n.py          message catalog (en, fr)
      mail.py          Mailer protocol, ConsoleMailer
      db/base.py       Base, mixins, naming convention
      db/types.py      pg_enum()
      db/session.py    create_engine(), get_session, SessionDep
      audit/models.py  AuditLog
      audit/writer.py  write_audit()
      outbox/models.py OutboxEvent, ProcessedEvent
      outbox/events.py DomainEvent
      outbox/writer.py emit_event()
      outbox/registry.py HandlerRegistry
      outbox/processing.py process_event(), purge_dispatched_events()
      outbox/relay.py  relay_once(), run_relay(), listen_dsn()
    modules/identity/
      models.py        UserAccount, RefreshSession, AccessGrant
      schemas.py       request/response schemas + AccessRevoked, GrantCreated events
      repository.py    UserRepository, RefreshSessionRepository, AccessGrantRepository
      tokens.py        issue/decode access tokens, opaque tokens, hashing
      revocation.py    mark_revoked(), is_revoked()
      dependencies.py  get_current_actor, CurrentActor, require_permission
      sessions.py      SessionService (start / rotate / end)
      magic_link.py    MagicLinkService
      oidc.py          IdTokenClaims, OidcProvider, AuthlibOidcProvider
      oidc_login.py    OidcLoginService
      permissions.py   Permission, ROLE_PERMISSIONS, markdown export
      visibility.py    Visibility, VisibilityPolicy, require_visibility, unguarded_worker_routes
      grants.py        GrantService
      scim.py          ScimService
      router.py        all identity routes
      service.py       public facade for other modules
    worker/
      jobs.py          run_event_handler, purge_outbox, expire_access_grants
      settings.py      Arq WorkerSettings
  tests/
    conftest.py, support.py
    unit/ integration/ api/                  # see each task
```

---

### Task 1: Backend scaffold, settings, database, core tables, health check

**Files:**
- Move: `requirements.txt` → `backend/requirements.txt`, `requirements-dev.txt` → `backend/requirements-dev.txt`
- Modify: `backend/requirements-dev.txt`
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/.env.example`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/0001_core.py`
- Create: `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/models_registry.py`
- Create: `backend/app/core/__init__.py`, `config.py`, `enums.py`, `time.py`, `deps.py`, `health.py`
- Create: `backend/app/core/db/__init__.py`, `base.py`, `types.py`, `session.py`
- Create: `backend/app/core/audit/__init__.py`, `models.py`; `backend/app/core/outbox/__init__.py`, `models.py`
- Create: `backend/app/modules/__init__.py`, `backend/app/worker/__init__.py`, `backend/app/wiring.py` (placeholder)
- Test: `backend/tests/__init__.py`, `tests/conftest.py`, `tests/support.py`, `tests/api/__init__.py`, `tests/api/test_health.py`, `tests/integration/__init__.py`, `tests/integration/test_migrations.py`, `tests/unit/__init__.py`

**Interfaces:**
- Produces: `Settings` (all fields below), `get_settings()`; `UserRole`, `AuthProvider`, `AccountStatus`; `utcnow() -> datetime`; `Base`, `UUIDPrimaryKeyMixin`, `TimestampMixin`; `pg_enum(enum_cls) -> sa.Enum`; `create_engine(settings) -> AsyncEngine`; `get_session`, `SessionDep`; `SettingsDep`, `RedisDep`; `AuditLog`, `OutboxEvent`, `ProcessedEvent` models; `create_app(settings=None, *, engine=None, redis=None) -> FastAPI`; test fixtures `postgres`, `database_url`, `settings`, `db_engine`, `session`, `sessionmaker`, `redis`, `app`, `client`; `tests.support.alembic_config(url) -> Config`.

- [ ] **Step 1: Move dependency files, add dev dependencies, create venv**

```bash
mkdir -p backend
git mv requirements.txt backend/requirements.txt
git mv requirements-dev.txt backend/requirements-dev.txt
```

Replace the contents of `backend/requirements-dev.txt` with:

```text
# Bonarda Works — Backend dependencies (development / test only)
# Install alongside requirements.txt: pip install -r requirements.txt -r requirements-dev.txt

-r requirements.txt

# --- Testing ---
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
httpx==0.27.2            # also used as the async test client
factory-boy==3.3.1
faker==29.0.0
testcontainers[postgres]==4.8.1   # real Postgres for integration tests (outbox, triggers)
fakeredis==2.25.1                 # in-process Redis for API tests
locust==2.31.8                    # pre-launch load test (NFR-1.1)

# --- Linting & typing ---
ruff==0.6.9
mypy==1.11.2
import-linter==2.1                # module boundary contracts

# --- Local tooling ---
pre-commit==3.8.0
watchfiles==0.24.0       # used by uvicorn --reload
```

(`types-redis` is removed on purpose: its stubs target redis-py 4 and conflict with redis-py 5's inline types.)

```bash
cd backend
py -3.12 -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Create `.gitignore` at the repository root:

```text
__pycache__/
*.pyc
.venv/
.env
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
node_modules/
dist/
```

- [ ] **Step 2: Create tool configuration**

`backend/pyproject.toml`:

```toml
[project]
name = "bonarda-backend"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "RUF"]
ignore = ["RUF001", "RUF002", "RUF003"]  # em dashes and accented French text are intended

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends", "fastapi.Query", "fastapi.Header", "fastapi.Cookie"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = false
plugins = ["pydantic.mypy"]
packages = ["app"]

[[tool.mypy.overrides]]
module = ["arq.*", "asyncpg.*", "authlib.*", "redis.*", "testcontainers.*", "fakeredis.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]

[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "core depends on nothing above it"
type = "forbidden"
source_modules = ["app.core"]
forbidden_modules = ["app.modules", "app.main", "app.worker", "app.wiring", "app.models_registry"]

[[tool.importlinter.contracts]]
name = "modules do not depend on the composition root"
type = "forbidden"
source_modules = ["app.modules"]
forbidden_modules = ["app.main", "app.worker", "app.wiring", "app.models_registry"]
```

`backend/.env.example`:

```text
ENV=dev
DATABASE_URL=postgresql+asyncpg://bonarda:bonarda@localhost:5432/bonarda
REDIS_URL=redis://localhost:6379/0
PUBLIC_APP_URL=http://localhost:5173
JWT_SIGNING_KEY=change-me-to-32-plus-random-bytes-please
COOKIE_SECURE=false
OIDC_ISSUER_URL=http://localhost:8080/realms/bonarda
OIDC_CLIENT_ID=bonarda-api
OIDC_CLIENT_SECRET=change-me
OIDC_REDIRECT_URL=http://localhost:8000/api/v1/auth/oidc/callback
OIDC_GROUP_ROLE_MAP={"bonarda-pm":"pm","bonarda-people-ops":"people_ops","bonarda-finance":"finance","bonarda-admin":"admin"}
SCIM_BEARER_TOKEN=change-me
```

- [ ] **Step 3: Write the core kernel files**

`backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/db/__init__.py`, `backend/app/core/audit/__init__.py`, `backend/app/core/outbox/__init__.py`, `backend/app/modules/__init__.py`, `backend/app/worker/__init__.py`: empty files.

`backend/app/wiring.py` (placeholder so the import-linter contracts can name it; Task 4 fills it in):

```python
"""Composition root: the only place that knows every module's handlers."""
```

`backend/app/core/enums.py`:

```python
import enum


class UserRole(enum.StrEnum):
    PM = "pm"
    PEOPLE_OPS = "people_ops"
    FINANCE = "finance"
    WORKER = "worker"
    ADMIN = "admin"


class AuthProvider(enum.StrEnum):
    CORPORATE_SSO = "corporate_sso"  # FR-9.1
    MAGIC_LINK = "magic_link"  # FR-9.2


class AccountStatus(enum.StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"  # SCIM deactivation (FR-9.12)
```

`backend/app/core/time.py`:

```python
from datetime import UTC, datetime


def utcnow() -> datetime:
    """The only clock the application uses — always timezone-aware UTC."""
    return datetime.now(UTC)
```

`backend/app/core/config.py`:

```python
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import UserRole


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str
    db_pool_size: int = 10
    redis_url: str
    public_app_url: str

    jwt_signing_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 600
    staff_idle_timeout_seconds: int = 1_800
    staff_session_max_seconds: int = 43_200
    worker_idle_timeout_seconds: int = 86_400
    worker_session_max_seconds: int = 2_592_000
    revocation_marker_ttl_seconds: int = 900
    cookie_secure: bool = True

    magic_link_ttl_seconds: int = 900
    magic_link_per_email_per_hour: int = 5
    magic_link_per_ip_per_hour: int = 20

    oidc_issuer_url: str
    oidc_client_id: str
    oidc_client_secret: SecretStr
    oidc_redirect_url: str
    oidc_required_amr: list[str] = Field(default_factory=lambda: ["mfa", "otp", "hwk", "swk"])
    oidc_accepted_acr: list[str] = Field(default_factory=list)
    oidc_group_role_map: dict[str, UserRole] = Field(default_factory=dict)
    oidc_max_age_seconds: int = 2_592_000

    scim_bearer_token: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

`backend/app/core/db/base.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.time import utcnow

# Deterministic constraint names so hand-written migrations match the models.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID keys: safe to expose, leak no ordering. The Python default is applied
    at flush — call `await session.flush()` before using a new object's id (e.g.
    as an audit target). The server default is a backstop for raw SQL inserts."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    # Python-side defaults: server-side onupdate values would be expired after
    # flush and lazy-loading them under asyncio raises MissingGreenlet.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
```

`backend/app/core/db/types.py`:

```python
import enum

import sqlalchemy as sa


def pg_enum(enum_cls: type[enum.Enum]) -> sa.Enum:
    """Native Postgres ENUM that stores member *values* ("people_ops"), not names."""
    return sa.Enum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
```

`backend/app/core/db/session.py`:

```python
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Commits once after the endpoint returns, so the
    domain write, its audit row and its outbox event succeed or fail together."""
    async with request.app.state.sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]
```

`backend/app/core/deps.py`:

```python
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
```

`backend/app/core/audit/models.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.time import utcnow


class AuditLog(Base):
    """Append-only (FR-7.3, FR-9.13, NFR-3.3). A trigger rejects UPDATE and
    DELETE. No foreign keys: audit rows must outlive the records they describe."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_audit_target", "target_type", "target_id", "occurred_at"),
        Index("ix_audit_time_brin", "occurred_at", postgresql_using="brin"),
    )
```

`backend/app/core/outbox/models.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.time import utcnow


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        unique=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    __table_args__ = (
        Index("ix_outbox_pending", "id", postgresql_where=text("dispatched_at IS NULL")),
    )


class ProcessedEvent(Base):
    """Handler-level dedupe: (event_id, handler) is inserted in the handler's own
    transaction, so a handler's effects happen at most once per event."""

    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    handler: Mapped[str] = mapped_column(String(80), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
```

`backend/app/models_registry.py`:

```python
"""Imports every ORM model so Base.metadata is complete for Alembic and tests."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models

__all__ = ["audit_models", "outbox_models"]
```

`backend/app/core/health.py`:

```python
from fastapi import APIRouter
from sqlalchemy import text

from app.core.db.session import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
```

`backend/app/main.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core import health
from app.core.config import Settings, get_settings
from app.core.db.session import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.redis.aclose()
    await app.state.engine.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    redis: Redis | None = None,
) -> FastAPI:
    """App factory. Run with `uvicorn app.main:create_app --factory`."""
    settings = settings or get_settings()
    app = FastAPI(title="Bonarda Works API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine or create_engine(settings)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)
    app.include_router(health.router)
    return app
```

- [ ] **Step 4: Set up Alembic and the first migration**

`backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`backend/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`backend/alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models_registry  # noqa: F401  (populates Base.metadata)
from app.core.config import get_settings
from app.core.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async())
```

`backend/alembic/versions/0001_core.py`:

```python
"""core tables: audit log, outbox, processed events

Revision ID: 0001_core
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(20), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_target", "audit_log", ["target_type", "target_id", "occurred_at"])
    op.create_index("ix_audit_time_brin", "audit_log", ["occurred_at"], postgresql_using="brin")

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )

    op.create_table(
        "processed_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("handler", sa.String(80), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("event_id", "handler", name="pk_processed_events"),
    )

    # Append-only enforcement. Only the retention role may delete audit rows
    # (spec §6.3); standing_changes gets the same trigger in Plan 3.
    op.execute(
        """
        CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'audit_log'
             AND current_user = 'bonarda_retention' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS forbid_mutation()")
    op.drop_table("processed_events")
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_time_brin", table_name="audit_log")
    op.drop_index("ix_audit_target", table_name="audit_log")
    op.drop_table("audit_log")
```

- [ ] **Step 5: Write test infrastructure and the failing tests**

`backend/tests/__init__.py`, `tests/api/__init__.py`, `tests/integration/__init__.py`, `tests/unit/__init__.py`: empty files.

`backend/tests/support.py`:

```python
from pathlib import Path

from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg
```

`backend/tests/conftest.py`:

```python
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

import app.models_registry  # noqa: F401
from app.core.config import Settings
from app.core.db.base import Base
from app.core.enums import UserRole
from app.main import create_app
from tests.support import alembic_config


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
```

`backend/tests/api/test_health.py`:

```python
from httpx import AsyncClient


async def test_health_reports_database_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
```

`backend/tests/integration/test_migrations.py`:

```python
import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from app.core.db.base import Base
from tests.support import alembic_config


async def test_head_creates_core_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {"audit_log", "outbox_events", "processed_events"} <= tables


async def test_models_match_migrations(db_engine: AsyncEngine) -> None:
    def diff(sync_conn: Connection) -> list[object]:
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return list(compare_metadata(ctx, Base.metadata))

    async with db_engine.connect() as conn:
        differences = await conn.run_sync(diff)
    assert differences == []


def test_downgrade_to_base_then_upgrade_round_trips(postgres: PostgresContainer) -> None:
    base_url: str = postgres.get_connection_url()
    roundtrip_url = base_url.rsplit("/", 1)[0] + "/roundtrip"

    async def recreate_database() -> None:
        engine = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text("DROP DATABASE IF EXISTS roundtrip"))
            await conn.execute(text("CREATE DATABASE roundtrip"))
        await engine.dispose()

    asyncio.run(recreate_database())
    cfg = alembic_config(roundtrip_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
```

- [ ] **Step 6: Run the tests**

Run: `pytest -v`
Expected: 4 passed. (If the first run fails with a Docker error, start Docker Desktop and re-run. First run pulls `postgres:16-alpine`.)

To confirm the migration test has teeth, temporarily change `sa.String(80)` to `sa.String(81)` for `outbox_events.event_type` in `0001_core.py`, run `pytest tests/integration/test_migrations.py::test_models_match_migrations -v`, see it FAIL with a `modify_type` difference, then revert the change.

- [ ] **Step 7: Run static checks**

Run: `ruff format . && ruff check . && mypy && lint-imports`
Expected: no errors; import-linter reports 2 contracts kept.

- [ ] **Step 8: Commit**

```bash
cd ..
git add .gitignore backend
git commit -m "feat(backend): scaffold app, settings, database and core tables

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
cd backend
```

---

### Task 2: Problem+json errors, correlation IDs, structured logging

**Files:**
- Create: `backend/app/core/context.py`, `backend/app/core/errors.py`, `backend/app/core/logging.py`, `backend/app/core/middleware.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/api/test_errors.py`

**Interfaces:**
- Consumes: `create_app` from Task 1.
- Produces: `get_correlation_id() -> str | None`; `correlation_scope(correlation_id: str | None)` context manager; `Actor(user_id: UUID, role: UserRole, worker_id: UUID | None = None)` frozen dataclass; `AppError` and subclasses `BadRequest(400)`, `Unauthorized(401)`, `Forbidden(403)`, `NotFound(404)`, `Conflict(409)`, `TooManyRequests(429)`, each constructed as `Err(detail: str | None = None, *, code: str | None = None)`; `install_error_handlers(app)`; `configure_logging(*, json_logs: bool)`; `CorrelationIdMiddleware`; header name `X-Correlation-ID`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_errors.py`:

```python
import re

import pytest
from fastapi import APIRouter, FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from app.core.errors import NotFound


class _Body(BaseModel):
    name: str


@pytest.fixture
def error_routes(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/_test/missing-worker")
    async def missing_worker() -> None:
        raise NotFound("Worker not found", code="worker_not_found")

    @router.post("/_test/validate")
    async def validate(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    app.include_router(router)


@pytest.mark.usefixtures("error_routes")
async def test_app_error_renders_problem_json(client: AsyncClient) -> None:
    response = await client.get("/_test/missing-worker")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "worker_not_found"
    assert body["type"] == "urn:bonarda:error:worker_not_found"
    assert body["detail"] == "Worker not found"
    assert body["instance"] == "/_test/missing-worker"
    assert body["correlation_id"] == response.headers["x-correlation-id"]


@pytest.mark.usefixtures("error_routes")
async def test_validation_error_renders_problem_json(client: AsyncClient) -> None:
    response = await client.post("/_test/validate", json={})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["loc"] == ["body", "name"]


async def test_unknown_route_renders_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_correlation_id_is_generated_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-correlation-id"])


async def test_valid_incoming_correlation_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Correlation-ID": "spa-req.42_a-b"})

    assert response.headers["x-correlation-id"] == "spa-req.42_a-b"


@pytest.mark.parametrize("hostile", ["a" * 65, "has space", "semi;colon", "quote\"d"])
async def test_hostile_correlation_id_is_replaced(client: AsyncClient, hostile: str) -> None:
    response = await client.get("/health", headers={"X-Correlation-ID": hostile})

    returned = response.headers["x-correlation-id"]
    assert returned != hostile
    assert re.fullmatch(r"[0-9a-f]{32}", returned)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.errors'`.

- [ ] **Step 3: Implement**

`backend/app/core/context.py`:

```python
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

import structlog

from app.core.enums import UserRole

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


@contextmanager
def correlation_scope(correlation_id: str | None) -> Iterator[None]:
    """Binds the correlation ID for audit rows, outbox events and log lines."""
    token = _correlation_id.set(correlation_id)
    try:
        with structlog.contextvars.bound_contextvars(correlation_id=correlation_id):
            yield
    finally:
        _correlation_id.reset(token)


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller. `worker_id` is set only for role WORKER."""

    user_id: UUID
    role: UserRole
    worker_id: UUID | None = None
```

`backend/app/core/errors.py`:

```python
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_correlation_id

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    title: str = "Internal server error"

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        self.detail = detail or self.title
        if code is not None:
            self.code = code
        super().__init__(self.detail)


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
    title = "Bad request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    title = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    title = "Forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Too many requests"


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:bonarda:error:{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": request.url.path,
        "correlation_id": get_correlation_id(),
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        exc = AppError()
    return problem_response(
        request, status=exc.status_code, code=exc.code, title=exc.title, detail=exc.detail
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return problem_response(
        request,
        status=422,
        code="validation_error",
        title="Request validation failed",
        detail="One or more fields are invalid",
        extra={"errors": jsonable_encoder(errors)},
    )


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = str(exc.detail) if isinstance(exc, StarletteHTTPException) else "Error"
    headers = exc.headers if isinstance(exc, StarletteHTTPException) else None
    return problem_response(
        request,
        status=status,
        code=_HTTP_CODES.get(status, "http_error"),
        title=HTTPStatus(status).phrase,
        detail=detail,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
```

`backend/app/core/logging.py`:

```python
import logging

import structlog


def configure_logging(*, json_logs: bool) -> None:
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
```

`backend/app/core/middleware.py`:

```python
import re
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import correlation_scope

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _incoming_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"x-correlation-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_ID.fullmatch(candidate) else None
    return None


class CorrelationIdMiddleware:
    """Pure ASGI middleware: accepts a safe incoming ID or generates one, binds it
    for the whole request, and returns it in the response header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = _incoming_id(scope) or uuid.uuid4().hex

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(CORRELATION_HEADER, correlation_id)
            await send(message)

        with correlation_scope(correlation_id):
            await self.app(scope, receive, send_with_header)
```

Replace `backend/app/main.py` with:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core import health
from app.core.config import Settings, get_settings
from app.core.db.session import create_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.redis.aclose()
    await app.state.engine.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    redis: Redis | None = None,
) -> FastAPI:
    """App factory. Run with `uvicorn app.main:create_app --factory`."""
    settings = settings or get_settings()
    configure_logging(json_logs=settings.env != "dev")
    app = FastAPI(title="Bonarda Works API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine or create_engine(settings)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)
    install_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(health.router)
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_errors.py -v`
Expected: 9 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(core): problem+json errors, correlation IDs and structured logging

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Audit writer and outbox writer

**Files:**
- Create: `backend/app/core/audit/writer.py`, `backend/app/core/outbox/events.py`, `backend/app/core/outbox/writer.py`
- Test: `backend/tests/integration/test_audit_and_outbox.py`

**Interfaces:**
- Consumes: `AuditLog`, `OutboxEvent` (Task 1); `Actor`, `get_correlation_id`, `correlation_scope` (Task 2).
- Produces:
  - `async def write_audit(session: AsyncSession, *, actor: Actor | None, action: str, target_type: str, target_id: UUID, before: Mapping[str, Any] | None = None, after: Mapping[str, Any] | None = None, reason: str | None = None) -> AuditLog` — `actor=None` records `actor_role="system"`.
  - `class DomainEvent(BaseModel)` — frozen; subclasses declare `event_type: ClassVar[str]`; field `aggregate_id: UUID`.
  - `async def emit_event(session: AsyncSession, event: DomainEvent) -> OutboxEvent`
  - `OUTBOX_CHANNEL = "outbox"` (Postgres NOTIFY channel).

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_audit_and_outbox.py`:

```python
from typing import ClassVar
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.audit.writer import write_audit
from app.core.context import Actor, correlation_scope
from app.core.enums import UserRole
from app.core.outbox.events import DomainEvent
from app.core.outbox.models import OutboxEvent
from app.core.outbox.writer import emit_event


class SomethingHappened(DomainEvent):
    event_type: ClassVar[str] = "test.something_happened"
    detail: str


async def test_write_audit_persists_actor_target_and_correlation(session: AsyncSession) -> None:
    actor = Actor(user_id=uuid4(), role=UserRole.PEOPLE_OPS)
    target_id = uuid4()

    with correlation_scope("corr-123"):
        await write_audit(
            session,
            actor=actor,
            action="access_grant.created",
            target_type="access_grant",
            target_id=target_id,
            after={"reason": "cross-team cover"},
            reason="cross-team cover",
        )
    await session.commit()

    row = (await session.scalars(select(AuditLog))).one()
    assert row.actor_id == actor.user_id
    assert row.actor_role == "people_ops"
    assert row.action == "access_grant.created"
    assert row.target_id == target_id
    assert row.after == {"reason": "cross-team cover"}
    assert row.correlation_id == "corr-123"


async def test_system_actor_is_recorded_as_system(session: AsyncSession) -> None:
    await write_audit(
        session, actor=None, action="grant.expired", target_type="access_grant", target_id=uuid4()
    )
    await session.commit()

    row = (await session.scalars(select(AuditLog))).one()
    assert row.actor_id is None
    assert row.actor_role == "system"


async def _one_audit_row(session: AsyncSession) -> None:
    await write_audit(session, actor=None, action="x", target_type="t", target_id=uuid4())
    await session.commit()


async def test_audit_log_rejects_update(session: AsyncSession) -> None:
    await _one_audit_row(session)

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(update(AuditLog).values(reason="tampered"))


async def test_audit_log_rejects_delete(session: AsyncSession) -> None:
    await _one_audit_row(session)

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(AuditLog))


async def test_emit_event_persists_type_payload_and_correlation(session: AsyncSession) -> None:
    aggregate_id = uuid4()

    with correlation_scope("corr-456"):
        await emit_event(session, SomethingHappened(aggregate_id=aggregate_id, detail="hello"))
    await session.commit()

    row = (await session.scalars(select(OutboxEvent))).one()
    assert row.event_type == "test.something_happened"
    assert row.aggregate_id == aggregate_id
    assert row.payload == {"aggregate_id": str(aggregate_id), "detail": "hello"}
    assert row.correlation_id == "corr-456"
    assert row.dispatched_at is None
    assert row.attempts == 0


async def test_audit_and_event_roll_back_together(session: AsyncSession) -> None:
    await write_audit(session, actor=None, action="x", target_type="t", target_id=uuid4())
    await emit_event(session, SomethingHappened(aggregate_id=uuid4(), detail="lost"))
    await session.rollback()

    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_audit_and_outbox.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.audit.writer'`.

- [ ] **Step 3: Implement**

`backend/app/core/audit/writer.py`:

```python
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.context import Actor, get_correlation_id


async def write_audit(
    session: AsyncSession,
    *,
    actor: Actor | None,
    action: str,
    target_type: str,
    target_id: UUID,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    """Adds an audit row to the caller's session. It commits with the change it
    describes — never call this on a different session from the domain write."""
    entry = AuditLog(
        actor_id=actor.user_id if actor else None,
        actor_role=actor.role.value if actor else "system",
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=dict(before) if before is not None else None,
        after=dict(after) if after is not None else None,
        reason=reason,
        correlation_id=get_correlation_id(),
    )
    session.add(entry)
    return entry
```

`backend/app/core/outbox/events.py`:

```python
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DomainEvent(BaseModel):
    """Base for events published through the outbox. Subclasses set a unique
    `event_type` like "engagements.engagement_created" and add payload fields."""

    model_config = ConfigDict(frozen=True)

    event_type: ClassVar[str]
    aggregate_id: UUID
```

`backend/app/core/outbox/writer.py`:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_correlation_id
from app.core.outbox.events import DomainEvent
from app.core.outbox.models import OutboxEvent

OUTBOX_CHANNEL = "outbox"


async def emit_event(session: AsyncSession, event: DomainEvent) -> OutboxEvent:
    """Adds the event to the caller's transaction. Postgres delivers the NOTIFY
    only if that transaction commits, so the relay never sees a rolled-back event."""
    row = OutboxEvent(
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        payload=event.model_dump(mode="json"),
        correlation_id=get_correlation_id(),
    )
    session.add(row)
    await session.execute(text("SELECT pg_notify(:channel, '')"), {"channel": OUTBOX_CHANNEL})
    return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_audit_and_outbox.py -v`
Expected: 6 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(core): transactional audit writer and outbox writer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Outbox relay, idempotent handler processing, Arq worker

**Files:**
- Create: `backend/app/core/outbox/registry.py`, `backend/app/core/outbox/processing.py`, `backend/app/core/outbox/relay.py`
- Create: `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`
- Modify: `backend/app/wiring.py`
- Test: `backend/tests/unit/test_registry.py`, `backend/tests/integration/test_relay.py`, `backend/tests/unit/test_worker_jobs.py`

**Interfaces:**
- Consumes: `OutboxEvent`, `ProcessedEvent` (Task 1); `emit_event`, `DomainEvent` (Task 3); `correlation_scope` (Task 2).
- Produces:
  - `Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]`
  - `class HandlerRegistry` with `register(event: type[DomainEvent] | str, name: str, handler: Handler) -> None` (raises `ValueError` on duplicate name), `handler_names_for(event_type: str) -> list[str]`, `get(name: str) -> Handler`.
  - `HANDLER_JOB = "run_event_handler"`; `BATCH_SIZE = 100`; `STUCK_AFTER_ATTEMPTS = 10`.
  - `async def relay_once(sessionmaker, registry, enqueue) -> int` — `enqueue(job_name, event_id: str, handler_name: str, *, _job_id: str)`.
  - `async def run_relay(sessionmaker, registry, enqueue, *, listen_dsn: str, stop: asyncio.Event, poll_interval: float = 2.0) -> None`
  - `def listen_dsn(database_url: str) -> str`
  - `async def process_event(sessionmaker, registry, event_id: UUID, handler_name: str) -> bool` — `False` if already processed.
  - `async def purge_dispatched_events(sessionmaker, *, older_than: timedelta) -> int`
  - `app.wiring.build_registry() -> HandlerRegistry`
  - Arq job `run_event_handler(ctx, event_id: str, handler_name: str) -> bool`; `MAX_HANDLER_TRIES = 5`; `DEAD_LETTER_KEY = "outbox:dead_letter"`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_registry.py`:

```python
from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.events import DomainEvent
from app.core.outbox.registry import HandlerRegistry


class Pinged(DomainEvent):
    event_type: ClassVar[str] = "test.pinged"


async def _noop(session: AsyncSession, payload: dict[str, Any]) -> None:
    return None


def test_registers_handlers_by_event_class_or_name() -> None:
    registry = HandlerRegistry()
    registry.register(Pinged, "a.first", _noop)
    registry.register("test.pinged", "b.second", _noop)

    assert registry.handler_names_for("test.pinged") == ["a.first", "b.second"]
    assert registry.get("a.first") is _noop
    assert registry.handler_names_for("test.unknown") == []


def test_duplicate_handler_name_is_rejected() -> None:
    registry = HandlerRegistry()
    registry.register(Pinged, "a.first", _noop)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(Pinged, "a.first", _noop)
```

`backend/tests/integration/test_relay.py`:

```python
from datetime import timedelta
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.outbox.events import DomainEvent
from app.core.outbox.models import OutboxEvent, ProcessedEvent
from app.core.outbox.processing import process_event, purge_dispatched_events
from app.core.outbox.registry import HandlerRegistry
from app.core.outbox.relay import HANDLER_JOB, STUCK_AFTER_ATTEMPTS, relay_once
from app.core.outbox.writer import emit_event
from app.core.time import utcnow


class WorkerPinged(DomainEvent):
    event_type: ClassVar[str] = "test.worker_pinged"
    note: str


class FakeEnqueue:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.fail = fail

    async def __call__(self, job: str, event_id: str, handler: str, *, _job_id: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.calls.append((job, event_id, handler, _job_id))


async def _noop(session: AsyncSession, payload: dict[str, Any]) -> None:
    return None


async def _emit(sm: async_sessionmaker[AsyncSession], note: str = "hi") -> UUID:
    async with sm() as s, s.begin():
        row = await emit_event(s, WorkerPinged(aggregate_id=uuid4(), note=note))
    return row.event_id


@pytest.fixture
def registry() -> HandlerRegistry:
    r = HandlerRegistry()
    r.register(WorkerPinged, "roster.refresh", _noop)
    r.register(WorkerPinged, "notify.worker", _noop)
    return r


async def test_relay_enqueues_every_handler_with_deterministic_job_id(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    event_id = await _emit(sessionmaker)
    enqueue = FakeEnqueue()

    dispatched = await relay_once(sessionmaker, registry, enqueue)

    assert dispatched == 1
    assert enqueue.calls == [
        (HANDLER_JOB, str(event_id), "roster.refresh", f"{event_id}:roster.refresh"),
        (HANDLER_JOB, str(event_id), "notify.worker", f"{event_id}:notify.worker"),
    ]
    async with sessionmaker() as s:
        row = (await s.scalars(select(OutboxEvent))).one()
    assert row.dispatched_at is not None


async def test_relay_marks_events_without_handlers_dispatched(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _emit(sessionmaker)

    await relay_once(sessionmaker, HandlerRegistry(), FakeEnqueue())

    async with sessionmaker() as s:
        row = (await s.scalars(select(OutboxEvent))).one()
    assert row.dispatched_at is not None


async def test_relay_skips_already_dispatched_events(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    await _emit(sessionmaker)
    await relay_once(sessionmaker, registry, FakeEnqueue())
    second = FakeEnqueue()

    assert await relay_once(sessionmaker, registry, second) == 0
    assert second.calls == []


async def test_relay_keeps_event_pending_and_counts_attempts_when_enqueue_fails(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    await _emit(sessionmaker)

    await relay_once(sessionmaker, registry, FakeEnqueue(fail=True))
    await relay_once(sessionmaker, registry, FakeEnqueue(fail=True))

    async with sessionmaker() as s:
        row = (await s.scalars(select(OutboxEvent))).one()
    assert row.dispatched_at is None
    assert row.attempts == 2
    assert STUCK_AFTER_ATTEMPTS == 10


async def test_process_event_runs_handler_exactly_once(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seen: list[dict[str, Any]] = []

    async def record(session: AsyncSession, payload: dict[str, Any]) -> None:
        seen.append(payload)

    registry = HandlerRegistry()
    registry.register(WorkerPinged, "test.record", record)
    event_id = await _emit(sessionmaker, note="once")

    first = await process_event(sessionmaker, registry, event_id, "test.record")
    second = await process_event(sessionmaker, registry, event_id, "test.record")

    assert (first, second) == (True, False)
    assert [p["note"] for p in seen] == ["once"]


async def test_failed_handler_releases_its_claim_for_retry(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    calls = 0

    async def flaky(session: AsyncSession, payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider timeout")

    registry = HandlerRegistry()
    registry.register(WorkerPinged, "test.flaky", flaky)
    event_id = await _emit(sessionmaker)

    with pytest.raises(RuntimeError):
        await process_event(sessionmaker, registry, event_id, "test.flaky")
    assert await process_event(sessionmaker, registry, event_id, "test.flaky") is True
    assert calls == 2


async def test_purge_removes_only_old_dispatched_events(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry
) -> None:
    old_id = await _emit(sessionmaker, note="old")
    await _emit(sessionmaker, note="pending")
    async with sessionmaker() as s, s.begin():
        await s.execute(
            update(OutboxEvent)
            .where(OutboxEvent.event_id == old_id)
            .values(dispatched_at=utcnow() - timedelta(days=15))
        )
        s.add(ProcessedEvent(event_id=old_id, handler="x", processed_at=utcnow() - timedelta(days=15)))

    purged = await purge_dispatched_events(sessionmaker, older_than=timedelta(days=14))

    assert purged == 1
    async with sessionmaker() as s:
        remaining = (await s.scalars(select(OutboxEvent.payload))).all()
        processed = await s.scalar(select(func.count()).select_from(ProcessedEvent))
    assert [p["note"] for p in remaining] == ["pending"]
    assert processed == 0
```

`backend/tests/unit/test_worker_jobs.py`:

```python
import json
from typing import Any
from uuid import uuid4

import pytest
from arq.worker import Retry
from fakeredis import aioredis as fake_aioredis

from app.worker import jobs


@pytest.fixture
def failing_process_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(jobs, "process_event", boom)


@pytest.mark.usefixtures("failing_process_event")
async def test_failed_handler_is_retried_with_backoff() -> None:
    ctx = {"sessionmaker": None, "registry": None, "job_try": 2, "redis": None}

    with pytest.raises(Retry) as excinfo:
        await jobs.run_event_handler(ctx, str(uuid4()), "roster.refresh")

    assert excinfo.value.defer_score == 4_000  # 2 ** job_try seconds, in ms


@pytest.mark.usefixtures("failing_process_event")
async def test_handler_is_dead_lettered_on_final_try() -> None:
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    event_id = str(uuid4())
    ctx = {"sessionmaker": None, "registry": None, "job_try": jobs.MAX_HANDLER_TRIES, "redis": redis}

    result = await jobs.run_event_handler(ctx, event_id, "roster.refresh")

    assert result is False
    entry = json.loads((await redis.lrange(jobs.DEAD_LETTER_KEY, 0, -1))[0])
    assert entry["event_id"] == event_id
    assert entry["handler"] == "roster.refresh"
    assert "handler exploded" in entry["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_registry.py tests/integration/test_relay.py tests/unit/test_worker_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.outbox.registry'`.

- [ ] **Step 3: Implement**

`backend/app/core/outbox/registry.py`:

```python
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.events import DomainEvent

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


class HandlerRegistry:
    """Maps event types to named handlers. Names are global and stable
    ("roster.refresh_worker") because they form part of the Arq job ID."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._by_event: defaultdict[str, list[str]] = defaultdict(list)

    def register(self, event: type[DomainEvent] | str, name: str, handler: Handler) -> None:
        event_type = event if isinstance(event, str) else event.event_type
        if name in self._handlers:
            raise ValueError(f"handler {name!r} already registered")
        self._handlers[name] = handler
        self._by_event[event_type].append(name)

    def handler_names_for(self, event_type: str) -> list[str]:
        return list(self._by_event.get(event_type, []))

    def get(self, name: str) -> Handler:
        return self._handlers[name]
```

`backend/app/core/outbox/processing.py`:

```python
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import correlation_scope
from app.core.outbox.models import OutboxEvent, ProcessedEvent
from app.core.outbox.registry import HandlerRegistry
from app.core.time import utcnow


async def process_event(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    event_id: UUID,
    handler_name: str,
) -> bool:
    """Runs one handler for one event, at most once. The claim row and the
    handler's writes share a transaction: if the handler raises, both roll back
    and a retry runs it again. Returns False if it already ran."""
    async with sessionmaker() as session, session.begin():
        claimed = await session.scalar(
            pg_insert(ProcessedEvent)
            .values(event_id=event_id, handler=handler_name)
            .on_conflict_do_nothing()
            .returning(ProcessedEvent.event_id)
        )
        if claimed is None:
            return False
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id))
        if event is None:
            raise LookupError(f"outbox event {event_id} not found")
        with correlation_scope(event.correlation_id):
            await registry.get(handler_name)(session, event.payload)
    return True


async def purge_dispatched_events(
    sessionmaker: async_sessionmaker[AsyncSession], *, older_than: timedelta
) -> int:
    cutoff = utcnow() - older_than
    async with sessionmaker() as session, session.begin():
        result = await session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.dispatched_at.is_not(None), OutboxEvent.dispatched_at < cutoff
            )
        )
        await session.execute(delete(ProcessedEvent).where(ProcessedEvent.processed_at < cutoff))
    return cast(CursorResult[Any], result).rowcount
```

`backend/app/core/outbox/relay.py`:

```python
import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import asyncpg
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.outbox.models import OutboxEvent
from app.core.outbox.registry import HandlerRegistry
from app.core.outbox.writer import OUTBOX_CHANNEL
from app.core.time import utcnow

HANDLER_JOB = "run_event_handler"
BATCH_SIZE = 100
STUCK_AFTER_ATTEMPTS = 10

Enqueue = Callable[..., Awaitable[object]]
log = structlog.get_logger(__name__)


def listen_dsn(database_url: str) -> str:
    """asyncpg.connect() needs a plain postgresql:// DSN."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def relay_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
) -> int:
    """Claims a batch of undispatched events (SKIP LOCKED, so several relays can
    run) and enqueues one Arq job per handler. The job ID makes re-enqueueing
    after a partial failure harmless. Returns the number of rows claimed."""
    async with sessionmaker() as session, session.begin():
        rows = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.dispatched_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            try:
                for name in registry.handler_names_for(row.event_type):
                    await enqueue(
                        HANDLER_JOB, str(row.event_id), name, _job_id=f"{row.event_id}:{name}"
                    )
            except Exception:
                row.attempts += 1
                level = log.error if row.attempts >= STUCK_AFTER_ATTEMPTS else log.warning
                level(
                    "outbox.enqueue_failed",
                    event_id=str(row.event_id),
                    event_type=row.event_type,
                    attempts=row.attempts,
                    exc_info=True,
                )
                continue
            row.dispatched_at = utcnow()
    return len(rows)


async def run_relay(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    enqueue: Enqueue,
    *,
    listen_dsn: str,
    stop: asyncio.Event,
    poll_interval: float = 2.0,
) -> None:
    """Wakes on NOTIFY outbox (immediate) or every poll_interval (fallback)."""
    wake = asyncio.Event()
    conn = await asyncpg.connect(listen_dsn)
    await conn.add_listener(OUTBOX_CHANNEL, lambda *_: wake.set())
    try:
        while not stop.is_set():
            wake.clear()
            try:
                claimed = await relay_once(sessionmaker, registry, enqueue)
            except Exception:
                log.exception("outbox.relay_failed")
                claimed = 0
            if claimed == BATCH_SIZE:
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=poll_interval)
    finally:
        await conn.close()
```

Replace `backend/app/wiring.py` with:

```python
"""Composition root: the only place that knows every module's handlers.
Later plans register their event handlers here."""

from app.core.outbox.registry import HandlerRegistry


def build_registry() -> HandlerRegistry:
    return HandlerRegistry()
```

`backend/app/worker/jobs.py`:

```python
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from arq.worker import Retry

from app.core.outbox.processing import process_event, purge_dispatched_events

MAX_HANDLER_TRIES = 5
DEAD_LETTER_KEY = "outbox:dead_letter"
log = structlog.get_logger(__name__)


async def run_event_handler(ctx: dict[str, Any], event_id: str, handler_name: str) -> bool:
    try:
        return await process_event(ctx["sessionmaker"], ctx["registry"], UUID(event_id), handler_name)
    except Exception as exc:
        job_try: int = ctx.get("job_try", 1)
        if job_try >= MAX_HANDLER_TRIES:
            await ctx["redis"].lpush(
                DEAD_LETTER_KEY,
                json.dumps({"event_id": event_id, "handler": handler_name, "error": repr(exc)}),
            )
            log.error("outbox.handler_dead_lettered", event_id=event_id, handler=handler_name)
            return False
        raise Retry(defer=2**job_try) from exc


async def purge_outbox(ctx: dict[str, Any]) -> int:
    return await purge_dispatched_events(ctx["sessionmaker"], older_than=timedelta(days=14))
```

`backend/app/worker/settings.py`:

```python
import asyncio
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.db.session import create_engine
from app.core.logging import configure_logging
from app.core.outbox.relay import listen_dsn, run_relay
from app.wiring import build_registry
from app.worker.jobs import MAX_HANDLER_TRIES, purge_outbox, run_event_handler


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(json_logs=settings.env != "dev")
    engine = create_engine(settings)
    ctx["engine"] = engine
    ctx["sessionmaker"] = async_sessionmaker(engine, expire_on_commit=False)
    ctx["registry"] = build_registry()
    ctx["relay_stop"] = asyncio.Event()
    ctx["relay_task"] = asyncio.create_task(
        run_relay(
            ctx["sessionmaker"],
            ctx["registry"],
            ctx["redis"].enqueue_job,
            listen_dsn=listen_dsn(settings.database_url),
            stop=ctx["relay_stop"],
        )
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["relay_stop"].set()
    await ctx["relay_task"]
    await ctx["engine"].dispose()


class WorkerSettings:
    """Run with `arq app.worker.settings.WorkerSettings`."""

    functions: ClassVar[list[Any]] = [run_event_handler]
    cron_jobs: ClassVar[list[Any]] = [cron(purge_outbox, hour={2}, minute={30})]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_HANDLER_TRIES
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_registry.py tests/integration/test_relay.py tests/unit/test_worker_jobs.py -v`
Expected: 11 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(core): outbox relay, idempotent handlers and Arq worker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Identity tables, access tokens, authenticated actor with revocation check

**Files:**
- Create: `backend/app/modules/identity/__init__.py`, `models.py`, `repository.py`, `tokens.py`, `revocation.py`, `dependencies.py`
- Create: `backend/alembic/versions/0002_identity.py`
- Modify: `backend/app/models_registry.py`, `backend/tests/support.py`
- Test: `backend/tests/unit/identity/__init__.py`, `tests/unit/identity/test_tokens.py`, `tests/api/identity/__init__.py`, `tests/api/identity/test_current_actor.py`

**Interfaces:**
- Consumes: `Base`, mixins, `pg_enum`, `Settings`, `SettingsDep`, `RedisDep`, `Actor`, `Unauthorized`, `utcnow`.
- Produces:
  - Models `UserAccount(email, role, auth_provider, status, oidc_subject, worker_id, can_view_governance, last_login_at)`, `RefreshSession(user_id, family_id, family_started_at, token_hash, amr, expires_at, revoked_at)`, `AccessGrant(granted_to_id, scoped_worker_id, granted_by_id, reason, expires_at, revoked_at)`.
  - `UserRepository(session)`: `get(user_id) -> UserAccount | None`, `get_by_email(email) -> UserAccount | None` (case/whitespace-insensitive), `get_by_oidc_subject(subject) -> UserAccount | None`, `add(user) -> UserAccount`.
  - `RefreshSessionRepository(session)`: `get_by_hash(token_hash)`, `add(row)`, `revoke_family(family_id, at)`, `revoke_all_for_user(user_id, at)`.
  - `AccessGrantRepository(session)`: `get(grant_id)`, `add(grant)`, `has_active(granted_to_id, worker_id, at) -> bool`, `list_active(*, granted_to_id: UUID | None, at) -> list[AccessGrant]`, `list_lapsed(at) -> list[AccessGrant]`.
  - `AccessClaims(user_id, role, worker_id, issued_at, amr)`; `issue_access_token(settings, *, user_id, role, worker_id, amr, now=None) -> str`; `decode_access_token(settings, token) -> AccessClaims` (raises `Unauthorized(code="invalid_token")`); `new_opaque_token() -> str`; `hash_token(token) -> str`.
  - `mark_revoked(redis, settings, user_id, at) -> None`; `is_revoked(redis, user_id, issued_at) -> bool` (fails open on Redis errors).
  - `get_current_actor`, `CurrentActor = Annotated[Actor, Depends(get_current_actor)]`.
  - Test helpers `make_user(session, *, role=UserRole.PM, email=None, status=AccountStatus.ACTIVE, oidc_subject=None, worker_id=None) -> UserAccount`, `bearer(settings, user, *, now=None) -> dict[str, str]`.

- [ ] **Step 1: Write the models, repository and migration**

`backend/app/modules/identity/__init__.py`: empty file.

`backend/app/modules/identity/models.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.core.enums import AccountStatus, AuthProvider, UserRole


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_accounts"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # lowercase
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole), nullable=False)
    auth_provider: Mapped[AuthProvider] = mapped_column(pg_enum(AuthProvider), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        pg_enum(AccountStatus),
        default=AccountStatus.ACTIVE,
        server_default=AccountStatus.ACTIVE.value,
        nullable=False,
    )
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    # FK to workers.id is added by Plan 2's migration, once the table exists.
    worker_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    can_view_governance: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per issued refresh token. Rotation revokes the row and inserts a
    new one in the same family; reuse of a revoked row revokes the family."""

    __tablename__ = "refresh_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    family_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amr: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default=text("'{}'"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_refresh_sessions_family_id", "family_id"),
        Index("ix_refresh_sessions_user_id", "user_id"),
    )


class AccessGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FR-9.5 — scoped, expiring detail visibility for a PM. Reads check
    expires_at, so a grant stops working the moment it expires (NFR-3.8)."""

    __tablename__ = "access_grants"

    granted_to_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # FK to workers.id is added by Plan 2's migration.
    scoped_worker_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_access_grants_lookup",
            "granted_to_id",
            "scoped_worker_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_access_grants_expiry", "expires_at", postgresql_where=text("revoked_at IS NULL")
        ),
    )
```

`backend/app/modules/identity/repository.py`:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import AccessGrant, RefreshSession, UserAccount


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID) -> UserAccount | None:
        return await self.session.get(UserAccount, user_id)

    async def get_by_email(self, email: str) -> UserAccount | None:
        return await self.session.scalar(
            select(UserAccount).where(UserAccount.email == normalize_email(email))
        )

    async def get_by_oidc_subject(self, subject: str) -> UserAccount | None:
        return await self.session.scalar(
            select(UserAccount).where(UserAccount.oidc_subject == subject)
        )

    def add(self, user: UserAccount) -> UserAccount:
        user.email = normalize_email(user.email)
        self.session.add(user)
        return user


class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_hash(self, token_hash: str) -> RefreshSession | None:
        return await self.session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )

    def add(self, row: RefreshSession) -> RefreshSession:
        self.session.add(row)
        return row

    async def revoke_family(self, family_id: UUID, at: datetime) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def revoke_all_for_user(self, user_id: UUID, at: datetime) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=at)
        )


class AccessGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, grant_id: UUID) -> AccessGrant | None:
        return await self.session.get(AccessGrant, grant_id)

    def add(self, grant: AccessGrant) -> AccessGrant:
        self.session.add(grant)
        return grant

    async def has_active(self, granted_to_id: UUID, worker_id: UUID, at: datetime) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        AccessGrant.granted_to_id == granted_to_id,
                        AccessGrant.scoped_worker_id == worker_id,
                        AccessGrant.revoked_at.is_(None),
                        AccessGrant.expires_at > at,
                    )
                )
            )
        )

    async def list_active(self, *, granted_to_id: UUID | None, at: datetime) -> list[AccessGrant]:
        stmt = select(AccessGrant).where(
            AccessGrant.revoked_at.is_(None), AccessGrant.expires_at > at
        )
        if granted_to_id is not None:
            stmt = stmt.where(AccessGrant.granted_to_id == granted_to_id)
        return list((await self.session.scalars(stmt.order_by(AccessGrant.expires_at))).all())

    async def list_lapsed(self, at: datetime) -> list[AccessGrant]:
        return list(
            (
                await self.session.scalars(
                    select(AccessGrant).where(
                        AccessGrant.revoked_at.is_(None), AccessGrant.expires_at <= at
                    )
                )
            ).all()
        )
```

Replace `backend/app/models_registry.py` with:

```python
"""Imports every ORM model so Base.metadata is complete for Alembic and tests."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models
from app.modules.identity import models as identity_models

__all__ = ["audit_models", "identity_models", "outbox_models"]
```

`backend/alembic/versions/0002_identity.py`:

```python
"""identity: user accounts, refresh sessions, access grants

Revision ID: 0002_identity
Revises: 0001_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_identity"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("pm", "people_ops", "finance", "worker", "admin", name="userrole"),
            nullable=False,
        ),
        sa.Column(
            "auth_provider",
            sa.Enum("corporate_sso", "magic_link", name="authprovider"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "revoked", name="accountstatus"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("oidc_subject", sa.String(255), nullable=True),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "can_view_governance", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_user_accounts"),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
        sa.UniqueConstraint("oidc_subject", name="uq_user_accounts_oidc_subject"),
        sa.UniqueConstraint("worker_id", name="uq_user_accounts_worker_id"),
    )

    op.create_table(
        "refresh_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "amr", postgresql.ARRAY(sa.String(20)), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_accounts.id"], name="fk_refresh_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
    )
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])

    op.create_table(
        "access_grants",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("granted_to_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scoped_worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_access_grants"),
        sa.ForeignKeyConstraint(
            ["granted_to_id"], ["user_accounts.id"], name="fk_access_grants_granted_to_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"], ["user_accounts.id"], name="fk_access_grants_granted_by_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_access_grants_lookup",
        "access_grants",
        ["granted_to_id", "scoped_worker_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_access_grants_expiry",
        "access_grants",
        ["expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("access_grants")
    op.drop_table("refresh_sessions")
    op.drop_table("user_accounts")
    op.execute("DROP TYPE accountstatus")
    op.execute("DROP TYPE authprovider")
    op.execute("DROP TYPE userrole")
```

- [ ] **Step 2: Run the migration tests**

Run: `pytest tests/integration/test_migrations.py -v`
Expected: 3 passed (the new models match migration `0002`).

- [ ] **Step 3: Add test helpers**

Append to `backend/tests/support.py`:

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from app.modules.identity.tokens import issue_access_token


async def make_user(
    session: AsyncSession,
    *,
    role: UserRole = UserRole.PM,
    email: str | None = None,
    status: AccountStatus = AccountStatus.ACTIVE,
    oidc_subject: str | None = None,
    worker_id: UUID | None = None,
) -> UserAccount:
    is_worker = role is UserRole.WORKER
    user = UserAccount(
        email=(email or f"{uuid4().hex[:10]}@example.com").strip().lower(),
        role=role,
        auth_provider=AuthProvider.MAGIC_LINK if is_worker else AuthProvider.CORPORATE_SSO,
        status=status,
        oidc_subject=oidc_subject if not is_worker else None,
        worker_id=(worker_id or uuid4()) if is_worker else None,
    )
    session.add(user)
    await session.commit()
    return user


def bearer(settings: Settings, user: UserAccount, *, now: datetime | None = None) -> dict[str, str]:
    token = issue_access_token(
        settings, user_id=user.id, role=user.role, worker_id=user.worker_id, amr=["test"], now=now
    )
    return {"Authorization": f"Bearer {token}"}
```

Move the new imports to the top of `tests/support.py` (ruff `I` will sort them).

- [ ] **Step 4: Write the failing tests**

`backend/tests/unit/identity/__init__.py`, `backend/tests/api/identity/__init__.py`: empty files.

`backend/tests/unit/identity/test_tokens.py`:

```python
from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow
from app.modules.identity.tokens import (
    decode_access_token,
    hash_token,
    issue_access_token,
    new_opaque_token,
)


def test_access_token_round_trips_claims(settings: Settings) -> None:
    user_id, worker_id = uuid4(), uuid4()

    token = issue_access_token(
        settings, user_id=user_id, role=UserRole.WORKER, worker_id=worker_id, amr=["email"]
    )
    claims = decode_access_token(settings, token)

    assert claims.user_id == user_id
    assert claims.role is UserRole.WORKER
    assert claims.worker_id == worker_id
    assert claims.amr == ["email"]


def test_expired_token_is_rejected(settings: Settings) -> None:
    token = issue_access_token(
        settings,
        user_id=uuid4(),
        role=UserRole.PM,
        worker_id=None,
        amr=[],
        now=utcnow() - timedelta(seconds=settings.access_token_ttl_seconds + 5),
    )

    with pytest.raises(Unauthorized) as excinfo:
        decode_access_token(settings, token)
    assert excinfo.value.code == "invalid_token"


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    other = settings.model_copy(
        update={"jwt_signing_key": SecretStr("another-key-that-is-32-bytes-long!!")}
    )
    token = issue_access_token(other, user_id=uuid4(), role=UserRole.PM, worker_id=None, amr=[])

    with pytest.raises(Unauthorized):
        decode_access_token(settings, token)


def test_token_without_access_type_is_rejected(settings: Settings) -> None:
    now = int(utcnow().timestamp())
    token = jwt.encode(
        {"sub": str(uuid4()), "role": "pm", "iat": now, "exp": now + 60, "typ": "refresh"},
        settings.jwt_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(Unauthorized):
        decode_access_token(settings, token)


def test_token_with_unknown_role_is_rejected(settings: Settings) -> None:
    now = int(utcnow().timestamp())
    token = jwt.encode(
        {"sub": str(uuid4()), "role": "superuser", "iat": now, "exp": now + 60, "typ": "access"},
        settings.jwt_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(Unauthorized):
        decode_access_token(settings, token)


def test_opaque_tokens_are_unique_and_hash_to_64_hex_chars() -> None:
    first, second = new_opaque_token(), new_opaque_token()

    assert first != second
    assert len(hash_token(first)) == 64
    assert hash_token(first) == hash_token(first)
```

`backend/tests/api/identity/test_current_actor.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/unit/identity tests/api/identity -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.identity.tokens'`.

- [ ] **Step 6: Implement**

`backend/app/modules/identity/tokens.py`:

```python
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    role: UserRole
    worker_id: UUID | None
    issued_at: datetime
    amr: list[str]


def issue_access_token(
    settings: Settings,
    *,
    user_id: UUID,
    role: UserRole,
    worker_id: UUID | None,
    amr: list[str],
    now: datetime | None = None,
) -> str:
    issued = int((now or utcnow()).timestamp())
    payload: dict[str, object] = {
        "sub": str(user_id),
        "role": role.value,
        "amr": amr,
        "iat": issued,
        "exp": issued + settings.access_token_ttl_seconds,
        "jti": uuid4().hex,
        "typ": "access",
    }
    if worker_id is not None:
        payload["wid"] = str(worker_id)
    return jwt.encode(
        payload, settings.jwt_signing_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    invalid = Unauthorized("Invalid or expired access token", code="invalid_token")
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "role"]},
        )
        if payload.get("typ") != "access":
            raise invalid
        return AccessClaims(
            user_id=UUID(payload["sub"]),
            role=UserRole(payload["role"]),
            worker_id=UUID(payload["wid"]) if payload.get("wid") else None,
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            amr=[str(a) for a in payload.get("amr", [])],
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise invalid from exc


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
```

`backend/app/modules/identity/revocation.py`:

```python
from datetime import datetime
from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

log = structlog.get_logger(__name__)


def _key(user_id: UUID) -> str:
    return f"revoked_after:{user_id}"


async def mark_revoked(redis: Redis, settings: Settings, user_id: UUID, at: datetime) -> None:
    """Tokens issued at or before `at` stop working immediately. The marker only
    needs to outlive the longest access token, so it expires on its own."""
    await redis.set(
        _key(user_id), str(int(at.timestamp())), ex=settings.revocation_marker_ttl_seconds
    )


async def is_revoked(redis: Redis, user_id: UUID, issued_at: datetime) -> bool:
    """Fails open: if Redis is unreachable the 10-minute token TTL still bounds
    revocation within the 15-minute NFR-3.5 target (spec §8.1)."""
    try:
        raw = await redis.get(_key(user_id))
    except (RedisError, OSError):
        log.warning("auth.revocation_check_unavailable", user_id=str(user_id))
        return False
    return raw is not None and int(issued_at.timestamp()) <= int(raw)
```

`backend/app/modules/identity/dependencies.py`:

```python
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.context import Actor
from app.core.deps import RedisDep, SettingsDep
from app.core.errors import Unauthorized
from app.modules.identity.revocation import is_revoked
from app.modules.identity.tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_actor(
    settings: SettingsDep,
    redis: RedisDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Actor:
    if credentials is None:
        raise Unauthorized("Missing bearer token", code="missing_token")
    claims = decode_access_token(settings, credentials.credentials)
    if await is_revoked(redis, claims.user_id, claims.issued_at):
        raise Unauthorized("Session has been revoked", code="session_revoked")
    return Actor(user_id=claims.user_id, role=claims.role, worker_id=claims.worker_id)


CurrentActor = Annotated[Actor, Depends(get_current_actor)]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/identity tests/api/identity -v`
Expected: 11 passed.

- [ ] **Step 8: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app alembic tests
git commit -m "feat(identity): accounts, access tokens and revocation-aware actor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Refresh sessions, `/auth/refresh`, `/auth/logout`, `/me`

**Files:**
- Create: `backend/app/modules/identity/schemas.py`, `sessions.py`, `router.py`, `service.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/api/identity/test_sessions.py`

**Interfaces:**
- Consumes: repositories, tokens (Task 5); `write_audit` (Task 3); `SessionDep`, `SettingsDep`.
- Produces:
  - `IssuedSession(access_token: str, refresh_token: str, expires_in: int, refresh_max_age: int)`.
  - `SessionService(session, settings)`: `start(user, *, amr: list[str]) -> IssuedSession`, `rotate(refresh_token) -> IssuedSession`, `end(refresh_token) -> None`. Error codes: `invalid_refresh`, `refresh_superseded` (reuse within 10 s), `refresh_reuse_detected`, `session_expired`, `account_inactive`.
  - `REUSE_GRACE = timedelta(seconds=10)`.
  - Schemas `TokenResponse(access_token, token_type="bearer", expires_in)`, `MeResponse(id, email, role, worker_id, can_view_governance)`.
  - Router `router` (prefix `/api/v1`), `REFRESH_COOKIE = "bonarda_refresh"`, `COOKIE_PATH = "/api/v1/auth"`, `set_refresh_cookie(response, settings, issued)`.
  - `app/modules/identity/service.py` facade re-exporting `CurrentActor`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/identity/test_sessions.py`:

```python
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
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
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
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
        await session.scalars(
            select(RefreshSession).where(RefreshSession.revoked_at.is_(None))
        )
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
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/identity/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.identity.router'`.

- [ ] **Step 3: Implement**

`backend/app/modules/identity/schemas.py`:

```python
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import UserRole


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
    worker_id: UUID | None
    can_view_governance: bool
```

`backend/app/modules/identity/sessions.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow
from app.modules.identity.models import RefreshSession, UserAccount
from app.modules.identity.repository import RefreshSessionRepository, UserRepository
from app.modules.identity.tokens import hash_token, issue_access_token, new_opaque_token

# Two tabs refreshing together present the same token twice. Inside this window
# the loser gets a retryable 401 instead of triggering theft detection.
REUSE_GRACE = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_max_age: int


class SessionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.refresh = RefreshSessionRepository(session)

    def _limits(self, role: UserRole) -> tuple[timedelta, timedelta]:
        s = self.settings
        if role is UserRole.WORKER:
            return (
                timedelta(seconds=s.worker_idle_timeout_seconds),
                timedelta(seconds=s.worker_session_max_seconds),
            )
        return (
            timedelta(seconds=s.staff_idle_timeout_seconds),
            timedelta(seconds=s.staff_session_max_seconds),
        )

    def _issue(
        self, user: UserAccount, *, family_id: UUID, started: datetime, amr: list[str]
    ) -> IssuedSession:
        now = utcnow()
        idle, cap = self._limits(user.role)
        expires_at = min(now + idle, started + cap)
        refresh_token = new_opaque_token()
        self.refresh.add(
            RefreshSession(
                user_id=user.id,
                family_id=family_id,
                family_started_at=started,
                token_hash=hash_token(refresh_token),
                amr=amr,
                expires_at=expires_at,
            )
        )
        access = issue_access_token(
            self.settings, user_id=user.id, role=user.role, worker_id=user.worker_id, amr=amr
        )
        return IssuedSession(
            access_token=access,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_ttl_seconds,
            refresh_max_age=int((expires_at - now).total_seconds()),
        )

    async def start(self, user: UserAccount, *, amr: list[str]) -> IssuedSession:
        now = utcnow()
        user.last_login_at = now
        return self._issue(user, family_id=uuid4(), started=now, amr=amr)

    async def rotate(self, refresh_token: str) -> IssuedSession:
        now = utcnow()
        current = await self.refresh.get_by_hash(hash_token(refresh_token))
        if current is None:
            raise Unauthorized("Unknown refresh token", code="invalid_refresh")
        if current.revoked_at is not None:
            if now - current.revoked_at <= REUSE_GRACE:
                raise Unauthorized(
                    "Session was refreshed elsewhere; retry", code="refresh_superseded"
                )
            await self.refresh.revoke_family(current.family_id, now)
            await write_audit(
                self.session,
                actor=None,
                action="auth.refresh_reuse_detected",
                target_type="user_account",
                target_id=current.user_id,
                after={"family_id": str(current.family_id)},
            )
            # Commit before raising: the error response must not roll back the
            # revocation, or a stolen token family would stay usable.
            await self.session.commit()
            raise Unauthorized("Refresh token reuse detected", code="refresh_reuse_detected")
        if current.expires_at <= now:
            raise Unauthorized("Session expired", code="session_expired")
        user = await self.users.get(current.user_id)
        if user is None or user.status is not AccountStatus.ACTIVE:
            raise Unauthorized("Account is not active", code="account_inactive")
        current.revoked_at = now
        return self._issue(
            user, family_id=current.family_id, started=current.family_started_at, amr=current.amr
        )

    async def end(self, refresh_token: str) -> None:
        current = await self.refresh.get_by_hash(hash_token(refresh_token))
        if current is not None:
            await self.refresh.revoke_family(current.family_id, utcnow())
```

`backend/app/modules/identity/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from app.core.config import Settings
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.core.errors import Unauthorized
from app.modules.identity.dependencies import CurrentActor
from app.modules.identity.repository import UserRepository
from app.modules.identity.schemas import MeResponse, TokenResponse
from app.modules.identity.sessions import IssuedSession, SessionService

router = APIRouter(prefix="/api/v1", tags=["identity"])

REFRESH_COOKIE = "bonarda_refresh"
COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, settings: Settings, issued: IssuedSession) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=issued.refresh_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> TokenResponse:
    if not refresh_token:
        raise Unauthorized("Missing refresh cookie", code="missing_refresh")
    issued = await SessionService(session, settings).rotate(refresh_token)
    set_refresh_cookie(response, settings, issued)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post("/auth/logout", status_code=204)
async def logout(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> None:
    if refresh_token:
        await SessionService(session, settings).end(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.get("/me")
async def me(actor: CurrentActor, session: SessionDep) -> MeResponse:
    user = await UserRepository(session).get(actor.user_id)
    if user is None:
        raise Unauthorized("Account no longer exists", code="account_inactive")
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        worker_id=user.worker_id,
        can_view_governance=user.can_view_governance,
    )
```

`backend/app/modules/identity/service.py`:

```python
"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.dependencies import CurrentActor

__all__ = ["CurrentActor"]
```

In `backend/app/main.py`, add the import and include the router (after `app.include_router(health.router)`):

```python
from app.modules.identity.router import router as identity_router
```

```python
    app.include_router(identity_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/identity/test_sessions.py -v`
Expected: 9 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(identity): rotating refresh sessions with reuse detection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Worker magic-link sign-in

**Files:**
- Create: `backend/app/core/i18n.py`, `backend/app/core/mail.py`, `backend/app/modules/identity/magic_link.py`
- Modify: `backend/app/modules/identity/schemas.py`, `backend/app/modules/identity/router.py`, `backend/app/main.py`
- Test: `backend/tests/unit/test_i18n.py`, `backend/tests/api/identity/test_magic_link.py`

**Interfaces:**
- Consumes: `SessionService`, `set_refresh_cookie`, `UserRepository`, `new_opaque_token`, `hash_token`, `write_audit`, `TooManyRequests`, `Unauthorized`.
- Produces:
  - `t(key: str, locale: str = "en", **params: object) -> str`; catalog keys `magic_link.subject`, `magic_link.body`.
  - `class Mailer(Protocol)`: `async def send(self, *, to: str, subject: str, body: str) -> None`; `ConsoleMailer`; `get_mailer(request) -> Mailer`; `MailerDep`. `app.state.mailer` set in `create_app` (tests replace it).
  - `MagicLinkService(session, redis, settings, mailer)`: `request(email, client_ip) -> None`, `verify(token) -> UserAccount`. Error codes `magic_link_rate_limited`, `magic_link_invalid`.
  - Routes `POST /api/v1/auth/magic-link` (202) and `POST /api/v1/auth/magic-link/verify` (200 `TokenResponse` + cookie).
  - Schemas `MagicLinkRequest(email: EmailStr)`, `MagicLinkVerify(token: str)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_i18n.py`:

```python
from app.core.i18n import t


def test_translates_with_parameters() -> None:
    assert "15" in t("magic_link.body", "fr", minutes=15, link="https://x")
    assert t("magic_link.subject", "fr") == "Votre lien de connexion Bonarda"


def test_unknown_locale_falls_back_to_english() -> None:
    assert t("magic_link.subject", "sw") == "Your Bonarda sign-in link"
```

`backend/tests/api/identity/test_magic_link.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_i18n.py tests/api/identity/test_magic_link.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.i18n'`.

- [ ] **Step 3: Implement**

`backend/app/core/i18n.py`:

```python
"""Server-side message catalog (NFR-8.1). The SPA owns UI strings; the backend
only needs text it sends itself, such as email."""

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "magic_link.subject": "Your Bonarda sign-in link",
        "magic_link.body": (
            "Use this link to sign in to your Bonarda passport. "
            "It works once and expires in {minutes} minutes:\n\n{link}\n\n"
            "If you did not ask for it, you can ignore this email."
        ),
    },
    "fr": {
        "magic_link.subject": "Votre lien de connexion Bonarda",
        "magic_link.body": (
            "Utilisez ce lien pour vous connecter à votre passeport Bonarda. "
            "Il ne fonctionne qu'une fois et expire dans {minutes} minutes :\n\n{link}\n\n"
            "Si vous ne l'avez pas demandé, ignorez cet e-mail."
        ),
    },
}
DEFAULT_LOCALE = "en"


def t(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    catalog = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE])
    template = catalog.get(key, MESSAGES[DEFAULT_LOCALE][key])
    return template.format(**params)
```

`backend/app/core/mail.py`:

```python
from typing import Annotated, Protocol

import structlog
from fastapi import Depends, Request

log = structlog.get_logger(__name__)


class Mailer(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    """Development only: writes mail to the log. Plan 6 wires SMTP (Mailpit)."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        log.info("mail.console", to=to, subject=subject, body=body)


def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer


MailerDep = Annotated[Mailer, Depends(get_mailer)]
```

`backend/app/modules/identity/magic_link.py`:

```python
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import AccountStatus, UserRole
from app.core.errors import TooManyRequests, Unauthorized
from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import UserRepository, normalize_email
from app.modules.identity.tokens import hash_token, new_opaque_token

TOKEN_PREFIX = "magiclink:"
log = structlog.get_logger(__name__)


class MagicLinkService:
    def __init__(
        self, session: AsyncSession, redis: Redis, settings: Settings, mailer: Mailer
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.mailer = mailer
        self.users = UserRepository(session)

    async def request(self, email: str, client_ip: str) -> None:
        """Always behaves the same whether or not the email exists, so the
        endpoint cannot be used to discover who works with Bonarda."""
        email = normalize_email(email)
        s = self.settings
        await self._limit(f"ml:rate:email:{hash_token(email)}", s.magic_link_per_email_per_hour)
        await self._limit(f"ml:rate:ip:{client_ip}", s.magic_link_per_ip_per_hour)
        user = await self.users.get_by_email(email)
        if user is None or user.role is not UserRole.WORKER or user.status is not AccountStatus.ACTIVE:
            log.info("auth.magic_link_not_sent")
            return
        token = new_opaque_token()
        await self.redis.set(TOKEN_PREFIX + hash_token(token), str(user.id), ex=s.magic_link_ttl_seconds)
        # The token travels in the URL fragment so it never reaches server logs.
        link = f"{s.public_app_url}/auth/verify#token={token}"
        minutes = s.magic_link_ttl_seconds // 60
        await self.mailer.send(
            to=user.email,
            subject=t("magic_link.subject"),
            body=t("magic_link.body", minutes=minutes, link=link),
        )

    async def _limit(self, key: str, limit: int) -> None:
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 3600)
        if count > limit:
            raise TooManyRequests(
                "Too many sign-in link requests; try again later", code="magic_link_rate_limited"
            )

    async def verify(self, token: str) -> UserAccount:
        invalid = Unauthorized("This sign-in link is invalid or has expired", code="magic_link_invalid")
        user_id = await self.redis.getdel(TOKEN_PREFIX + hash_token(token))
        if user_id is None:
            raise invalid
        user = await self.users.get(UUID(user_id))
        if user is None or user.status is not AccountStatus.ACTIVE:
            raise invalid
        await write_audit(
            self.session,
            actor=Actor(user_id=user.id, role=user.role, worker_id=user.worker_id),
            action="auth.magic_link_login",
            target_type="user_account",
            target_id=user.id,
        )
        return user
```

Append to `backend/app/modules/identity/schemas.py` (add `EmailStr` to the pydantic import):

```python
class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkVerify(BaseModel):
    token: str
```

Add to `backend/app/modules/identity/router.py` — imports:

```python
from fastapi import Request

from app.core.deps import RedisDep
from app.core.mail import MailerDep
from app.modules.identity.magic_link import MagicLinkService
from app.modules.identity.schemas import MagicLinkRequest, MagicLinkVerify
```

and routes:

```python
@router.post("/auth/magic-link", status_code=202)
async def request_magic_link(
    body: MagicLinkRequest,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    mailer: MailerDep,
) -> dict[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    await MagicLinkService(session, redis, settings, mailer).request(body.email, client_ip)
    return {"status": "accepted"}


@router.post("/auth/magic-link/verify")
async def verify_magic_link(
    body: MagicLinkVerify,
    response: Response,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    mailer: MailerDep,
) -> TokenResponse:
    user = await MagicLinkService(session, redis, settings, mailer).verify(body.token)
    issued = await SessionService(session, settings).start(user, amr=["email"])
    set_refresh_cookie(response, settings, issued)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)
```

In `backend/app/main.py` add `from app.core.mail import ConsoleMailer` and, after the redis line in `create_app`:

```python
    app.state.mailer = ConsoleMailer()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_i18n.py tests/api/identity/test_magic_link.py -v`
Expected: 9 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(identity): worker magic-link sign-in with rate limits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Staff sign-in via OIDC with MFA enforcement

**Files:**
- Create: `backend/app/modules/identity/oidc.py`, `backend/app/modules/identity/oidc_login.py`
- Modify: `backend/app/modules/identity/router.py`, `backend/app/main.py`
- Test: `backend/tests/api/identity/test_oidc_login.py`

**Interfaces:**
- Consumes: `SessionService`, `set_refresh_cookie`, `UserRepository`, `write_audit`, `BadRequest`, `Forbidden`, `Conflict`.
- Produces:
  - `IdTokenClaims(subject: str, email: str, amr: list[str], acr: str | None, groups: list[str])`.
  - `class OidcProvider(Protocol)`: `async authorization_url(*, state, nonce, code_verifier) -> str`; `async exchange_code(*, code, code_verifier, nonce) -> IdTokenClaims`.
  - `AuthlibOidcProvider(settings)` (real IdP; verified against Keycloak in Plan 6). `app.state.oidc_provider`.
  - `OidcLoginService(session, redis, settings, provider)`: `begin() -> str` (redirect URL), `complete(*, code, state) -> tuple[UserAccount, IdTokenClaims]`. Error codes `oidc_state_invalid`, `mfa_required`, `no_role_assigned`, `email_missing`, `email_conflict`, `account_inactive`, `oidc_error`.
  - Routes `GET /api/v1/auth/oidc/login` (302) and `GET /api/v1/auth/oidc/callback` (302 to `{public_app_url}/console` + refresh cookie).

Note: the spec lists OIDC discovery under `integrations`; it lives in `identity/oidc.py` because only identity uses it and the `integrations` module does not exist until Plan 2.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/identity/test_oidc_login.py`:

```python
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from app.modules.identity.oidc import IdTokenClaims
from app.modules.identity.router import REFRESH_COOKIE
from tests.support import make_user


@dataclass
class FakeOidcProvider:
    claims: IdTokenClaims = field(
        default_factory=lambda: IdTokenClaims(
            subject="kc-ama", email="Ama@Bonarda.works", amr=["pwd", "otp"], acr=None,
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
    user = (await session.scalars(select(UserAccount))).one()
    assert (user.email, user.role, user.auth_provider) == (
        "ama@bonarda.works", UserRole.PM, AuthProvider.CORPORATE_SSO
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
        subject="kc-ama", email="ama@bonarda.works", amr=["otp"], acr=None,
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
        subject="kc-ama", email="ama@bonarda.works", amr=["otp"], acr=None,
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

    replay = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})

    assert replay.status_code == 400
    assert replay.json()["code"] == "oidc_state_invalid"


async def test_idp_error_is_reported(client: AsyncClient, idp: FakeOidcProvider) -> None:
    response = await client.get(
        "/api/v1/auth/oidc/callback", params={"error": "access_denied", "state": "s"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "oidc_error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/identity/test_oidc_login.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.identity.oidc'`.

- [ ] **Step 3: Implement**

`backend/app/modules/identity/oidc.py`:

```python
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, jwt

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class IdTokenClaims:
    subject: str
    email: str
    amr: list[str]
    acr: str | None
    groups: list[str]


class OidcProvider(Protocol):
    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str: ...

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> IdTokenClaims: ...


class AuthlibOidcProvider:
    """Authorization-code flow with PKCE against the corporate IdP. Discovery and
    JWKS are fetched lazily on first use and cached for the process lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._metadata: dict[str, Any] | None = None
        self._jwks: Any = None

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is None:
            issuer = self._settings.oidc_issuer_url.rstrip("/")
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as http:
                meta = await http.get(f"{issuer}/.well-known/openid-configuration")
                meta.raise_for_status()
                metadata: dict[str, Any] = meta.json()
                keys = await http.get(metadata["jwks_uri"])
                keys.raise_for_status()
            self._jwks = JsonWebKey.import_key_set(keys.json())
            self._metadata = metadata
        return self._metadata

    def _client(self) -> AsyncOAuth2Client:
        s = self._settings
        return AsyncOAuth2Client(
            client_id=s.oidc_client_id,
            client_secret=s.oidc_client_secret.get_secret_value(),
            redirect_uri=s.oidc_redirect_url,
            scope="openid email profile",
            code_challenge_method="S256",
            timeout=10.0,
        )

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        metadata = await self._discover()
        async with self._client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=code_verifier,
                max_age=str(self._settings.oidc_max_age_seconds),  # NFR-3.6: ≤ 30 days
            )
        return str(url)

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> IdTokenClaims:
        metadata = await self._discover()
        async with self._client() as client:
            token = await client.fetch_token(
                metadata["token_endpoint"], code=code, code_verifier=code_verifier
            )
        claims = jwt.decode(
            token["id_token"],
            self._jwks,
            claims_options={
                "iss": {"essential": True, "value": metadata["issuer"]},
                "aud": {"essential": True, "value": self._settings.oidc_client_id},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate(leeway=30)
        return IdTokenClaims(
            subject=str(claims["sub"]),
            email=str(claims.get("email", "")),
            amr=[str(a) for a in claims.get("amr") or []],
            acr=str(claims["acr"]) if claims.get("acr") else None,
            # Keycloak sends full group paths ("/bonarda-pm").
            groups=[str(g).lstrip("/") for g in claims.get("groups") or []],
        )
```

`backend/app/modules/identity/oidc_login.py`:

```python
import json
import secrets

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.errors import BadRequest, Conflict, Forbidden
from app.modules.identity.models import UserAccount
from app.modules.identity.oidc import IdTokenClaims, OidcProvider
from app.modules.identity.repository import UserRepository, normalize_email

STATE_PREFIX = "oidc:state:"
STATE_TTL_SECONDS = 600
ROLE_PRECEDENCE = (UserRole.ADMIN, UserRole.PEOPLE_OPS, UserRole.FINANCE, UserRole.PM)


class OidcLoginService:
    def __init__(
        self, session: AsyncSession, redis: Redis, settings: Settings, provider: OidcProvider
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.provider = provider
        self.users = UserRepository(session)

    async def begin(self) -> str:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(48)
        await self.redis.set(
            STATE_PREFIX + state,
            json.dumps({"nonce": nonce, "code_verifier": code_verifier}),
            ex=STATE_TTL_SECONDS,
        )
        return await self.provider.authorization_url(
            state=state, nonce=nonce, code_verifier=code_verifier
        )

    async def complete(self, *, code: str, state: str) -> tuple[UserAccount, IdTokenClaims]:
        raw = await self.redis.getdel(STATE_PREFIX + state)
        if raw is None:
            raise BadRequest("Sign-in session expired; start again", code="oidc_state_invalid")
        pending = json.loads(raw)
        claims = await self.provider.exchange_code(
            code=code, code_verifier=pending["code_verifier"], nonce=pending["nonce"]
        )
        self._require_mfa(claims)
        role = self._role_for(claims.groups)
        return await self._upsert(claims, role), claims

    def _require_mfa(self, claims: IdTokenClaims) -> None:
        amr_ok = bool(set(claims.amr) & set(self.settings.oidc_required_amr))
        acr_ok = claims.acr is not None and claims.acr in self.settings.oidc_accepted_acr
        if not (amr_ok or acr_ok):
            raise Forbidden("Multi-factor authentication is required", code="mfa_required")

    def _role_for(self, groups: list[str]) -> UserRole:
        mapping = self.settings.oidc_group_role_map
        roles = {mapping[g] for g in groups if g in mapping}
        for role in ROLE_PRECEDENCE:
            if role in roles:
                return role
        raise Forbidden("No Bonarda role is assigned to this account", code="no_role_assigned")

    async def _upsert(self, claims: IdTokenClaims, role: UserRole) -> UserAccount:
        user = await self.users.get_by_oidc_subject(claims.subject)
        if user is None:
            if not claims.email:
                raise Forbidden("The identity provider sent no email", code="email_missing")
            if await self.users.get_by_email(claims.email) is not None:
                raise Conflict("Email already belongs to another account", code="email_conflict")
            user = self.users.add(
                UserAccount(
                    email=normalize_email(claims.email),
                    role=role,
                    auth_provider=AuthProvider.CORPORATE_SSO,
                    oidc_subject=claims.subject,
                )
            )
            await self.session.flush()  # assigns user.id for the audit row
            await write_audit(
                self.session,
                actor=None,
                action="user.provisioned",
                target_type="user_account",
                target_id=user.id,
                after={"email": user.email, "role": role.value},
            )
            return user
        if user.status is not AccountStatus.ACTIVE:
            raise Forbidden("This account has been deactivated", code="account_inactive")
        if user.role is not role:
            previous = user.role
            user.role = role
            await write_audit(
                self.session,
                actor=None,
                action="user.role_changed",
                target_type="user_account",
                target_id=user.id,
                before={"role": previous.value},
                after={"role": role.value},
                reason="idp_group_membership",
            )
        return user
```

Add to `backend/app/modules/identity/router.py` — imports:

```python
from fastapi.responses import RedirectResponse

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import BadRequest
from app.modules.identity.oidc import OidcProvider
from app.modules.identity.oidc_login import OidcLoginService
```

and code:

```python
def get_oidc_provider(request: Request) -> OidcProvider:
    return request.app.state.oidc_provider


OidcProviderDep = Annotated[OidcProvider, Depends(get_oidc_provider)]


@router.get("/auth/oidc/login")
async def oidc_login(
    session: SessionDep, redis: RedisDep, settings: SettingsDep, provider: OidcProviderDep
) -> RedirectResponse:
    url = await OidcLoginService(session, redis, settings, provider).begin()
    return RedirectResponse(url, status_code=302)


@router.get("/auth/oidc/callback")
async def oidc_callback(
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    provider: OidcProviderDep,
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error or not code:
        raise BadRequest("The identity provider did not complete sign-in", code="oidc_error")
    service = OidcLoginService(session, redis, settings, provider)
    user, claims = await service.complete(code=code, state=state)
    issued = await SessionService(session, settings).start(user, amr=claims.amr)
    await write_audit(
        session,
        actor=Actor(user_id=user.id, role=user.role),
        action="auth.sso_login",
        target_type="user_account",
        target_id=user.id,
        after={"amr": claims.amr},
    )
    response = RedirectResponse(f"{settings.public_app_url}/console", status_code=302)
    set_refresh_cookie(response, settings, issued)
    return response
```

Add `Depends` to the `fastapi` import in `router.py`.

In `backend/app/main.py` add `from app.modules.identity.oidc import AuthlibOidcProvider` and, after the mailer line:

```python
    app.state.oidc_provider = AuthlibOidcProvider(settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/identity/test_oidc_login.py -v`
Expected: 10 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(identity): staff OIDC sign-in with MFA enforcement and role mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Role permission matrix and generated documentation

**Files:**
- Create: `backend/app/modules/identity/permissions.py`, `docs/permissions.md` (generated)
- Modify: `backend/app/modules/identity/dependencies.py`, `backend/app/modules/identity/service.py`
- Test: `backend/tests/unit/identity/test_permissions.py`, `backend/tests/api/identity/test_require_permission.py`

**Interfaces:**
- Consumes: `CurrentActor`, `Forbidden`, `UserRole`.
- Produces:
  - `class Permission(StrEnum)` with the 20 members below.
  - `ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]]`; `has_permission(role, permission) -> bool`; `render_markdown() -> str`.
  - `require_permission(permission) -> Callable[..., Awaitable[Actor]]` (raises `Forbidden(code="permission_denied")`), exported from `identity.service` along with `Permission`.
  - CLI: `python -m app.modules.identity.permissions ../docs/permissions.md`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/identity/test_permissions.py`:

```python
from pathlib import Path

import pytest

from app.core.enums import UserRole
from app.modules.identity.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    has_permission,
    render_markdown,
)

DOCS_FILE = Path(__file__).resolve().parents[4] / "docs" / "permissions.md"


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (UserRole.PM, Permission.ENGAGEMENT_REACTIVATE, True),
        (UserRole.PM, Permission.ACCESS_GRANT_MANAGE, False),
        (UserRole.PM, Permission.AUDIT_READ, False),
        (UserRole.PEOPLE_OPS, Permission.ACCESS_GRANT_MANAGE, True),
        (UserRole.PEOPLE_OPS, Permission.ENGAGEMENT_REACTIVATE, False),
        (UserRole.WORKER, Permission.DISPUTE_FILE, True),
        (UserRole.WORKER, Permission.WORKER_READ, False),
        (UserRole.FINANCE, Permission.ENGAGEMENT_READ_BILLING, True),
        (UserRole.FINANCE, Permission.WORKER_READ, False),
        (UserRole.ADMIN, Permission.AUDIT_READ, True),
        (UserRole.ADMIN, Permission.DISPUTE_RESOLVE, False),
    ],
)
def test_role_matrix(role: UserRole, permission: Permission, allowed: bool) -> None:
    assert has_permission(role, permission) is allowed


def test_every_role_is_defined_and_every_permission_is_granted_somewhere() -> None:
    assert set(ROLE_PERMISSIONS) == set(UserRole)
    granted = set().union(*ROLE_PERMISSIONS.values())
    assert granted == set(Permission)


def test_generated_documentation_is_up_to_date() -> None:
    assert DOCS_FILE.read_text(encoding="utf-8") == render_markdown(), (
        "docs/permissions.md is stale — run from backend/: "
        "python -m app.modules.identity.permissions ../docs/permissions.md"
    )
```

`backend/tests/api/identity/test_require_permission.py`:

```python
import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.identity.service import Permission, require_permission
from tests.support import bearer, make_user


@pytest.fixture
def guarded_route(app: FastAPI) -> None:
    router = APIRouter()

    @router.post(
        "/_test/grants", dependencies=[Depends(require_permission(Permission.ACCESS_GRANT_MANAGE))]
    )
    async def create() -> dict[str, str]:
        return {"ok": "yes"}

    app.include_router(router)


pytestmark = pytest.mark.usefixtures("guarded_route")


async def test_role_with_permission_passes(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post("/_test/grants", headers=bearer(settings, ops))

    assert response.status_code == 200


async def test_role_without_permission_is_forbidden(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post("/_test/grants", headers=bearer(settings, pm))

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/identity/test_permissions.py tests/api/identity/test_require_permission.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.identity.permissions'`.

- [ ] **Step 3: Implement**

`backend/app/modules/identity/permissions.py`:

```python
"""Fixed role → permission matrix (FR-9.3). Roles are never inferred from job
titles. docs/permissions.md is generated from this file and checked in CI.

PM leadership governance access is the `can_view_governance` account flag,
checked by the governance module in addition to GOVERNANCE_READ (Plan 4)."""

import sys
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from app.core.enums import UserRole


class Permission(StrEnum):
    WORKER_READ_SELF = "worker:read_self"
    WORKER_UPDATE_SELF = "worker:update_self"
    WORKER_READ = "worker:read"  # always further limited by VisibilityPolicy
    WORKER_INVITE = "worker:invite"
    DISPUTE_FILE = "dispute:file"
    DISPUTE_RESOLVE = "dispute:resolve"
    PROJECT_MANAGE = "project:manage"
    PROJECT_STAFF_ASSIGN = "project:staff_assign"
    ROSTER_SEARCH = "roster:search"
    ENGAGEMENT_CREATE = "engagement:create"
    ENGAGEMENT_REACTIVATE = "engagement:reactivate"
    ENGAGEMENT_READ_BILLING = "engagement:read_billing"
    FEEDBACK_SUBMIT = "feedback:submit"
    FIRST_SHOT_REVIEW = "first_shot:review"
    ACCESS_GRANT_MANAGE = "access_grant:manage"
    POLICY_PROPOSE = "policy:propose"
    POLICY_ACTIVATE = "policy:activate"
    STANDING_OVERRIDE = "standing:override"
    GOVERNANCE_READ = "governance:read"
    AUDIT_READ = "audit:read"


P = Permission
ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = MappingProxyType(
    {
        UserRole.WORKER: frozenset({P.WORKER_READ_SELF, P.WORKER_UPDATE_SELF, P.DISPUTE_FILE}),
        UserRole.PM: frozenset(
            {
                P.WORKER_READ,
                P.WORKER_INVITE,
                P.PROJECT_MANAGE,
                P.ROSTER_SEARCH,
                P.ENGAGEMENT_CREATE,
                P.ENGAGEMENT_REACTIVATE,
                P.FEEDBACK_SUBMIT,
                P.FIRST_SHOT_REVIEW,
            }
        ),
        UserRole.PEOPLE_OPS: frozenset(
            {
                P.WORKER_READ,
                P.PROJECT_MANAGE,
                P.PROJECT_STAFF_ASSIGN,
                P.DISPUTE_RESOLVE,
                P.ACCESS_GRANT_MANAGE,
                P.POLICY_PROPOSE,
                P.POLICY_ACTIVATE,
                P.STANDING_OVERRIDE,
                P.GOVERNANCE_READ,
                P.AUDIT_READ,
            }
        ),
        UserRole.FINANCE: frozenset({P.ENGAGEMENT_READ_BILLING}),
        UserRole.ADMIN: frozenset({P.WORKER_READ, P.GOVERNANCE_READ, P.AUDIT_READ}),
    }
)
_ROLE_ORDER = (UserRole.PM, UserRole.PEOPLE_OPS, UserRole.FINANCE, UserRole.WORKER, UserRole.ADMIN)


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def render_markdown() -> str:
    header = "| Permission | " + " | ".join(r.value for r in _ROLE_ORDER) + " |"
    divider = "|---|" + "---|" * len(_ROLE_ORDER)
    rows = [
        f"| `{p.value}` | "
        + " | ".join("✓" if has_permission(r, p) else "" for r in _ROLE_ORDER)
        + " |"
        for p in Permission
    ]
    return "\n".join(
        [
            "# Role permission matrix",
            "",
            "Generated from `backend/app/modules/identity/permissions.py`.",
            "Do not edit by hand; from `backend/` run:",
            "",
            "    python -m app.modules.identity.permissions ../docs/permissions.md",
            "",
            "`worker:read` is further limited per worker by the visibility policy",
            "(spec §7.1).",
            "",
            header,
            divider,
            *rows,
            "",
        ]
    )


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(render_markdown(), encoding="utf-8", newline="\n")
```

Append to `backend/app/modules/identity/dependencies.py` (add `from collections.abc import Awaitable, Callable`, `from app.core.errors import Forbidden`, and `from app.modules.identity.permissions import Permission, has_permission`):

```python
def require_permission(permission: Permission) -> Callable[..., Awaitable[Actor]]:
    async def dependency(actor: CurrentActor) -> Actor:
        if not has_permission(actor.role, permission):
            raise Forbidden(f"Missing permission {permission.value}", code="permission_denied")
        return actor

    return dependency
```

Replace `backend/app/modules/identity/service.py` with:

```python
"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.dependencies import CurrentActor, require_permission
from app.modules.identity.permissions import Permission

__all__ = ["CurrentActor", "Permission", "require_permission"]
```

Generate the documentation:

```bash
python -m app.modules.identity.permissions ../docs/permissions.md
```

Open `../docs/permissions.md` and check that it holds a 20-row table whose ticks match `ROLE_PERMISSIONS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/identity/test_permissions.py tests/api/identity/test_require_permission.py -v`
Expected: 15 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
cd ..
git add backend/app backend/tests docs/permissions.md
git commit -m "feat(identity): role permission matrix with generated documentation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
cd backend
```

---

### Task 10: Visibility policy and access grants

**Files:**
- Create: `backend/app/modules/identity/visibility.py`, `backend/app/modules/identity/grants.py`
- Modify: `backend/app/modules/identity/schemas.py`, `router.py`, `service.py`, `backend/app/wiring.py`, `backend/app/main.py`, `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`
- Test: `backend/tests/integration/test_visibility_policy.py`, `backend/tests/api/identity/test_access_grants.py`, `backend/tests/api/test_visibility_guard.py`

**Interfaces:**
- Consumes: `AccessGrantRepository`, `UserRepository`, `CurrentActor`, `require_permission`, `write_audit`, `emit_event`, `DomainEvent`.
- Produces:
  - `class Visibility(IntEnum)`: `NONE=0, SUMMARY=1, DETAIL=2, SELF=3`.
  - `VisibilitySource = Callable[[AsyncSession, Actor, UUID], Awaitable[Visibility]]` — later plans register sources (engagement relationship, first-shot shortlist) in `app.wiring.visibility_sources()`.
  - `VisibilityPolicy(sources: Sequence[VisibilitySource] = ())`: `level(session, actor, worker_id) -> Visibility`. `app.state.visibility_policy`.
  - `require_visibility(minimum: Visibility)` dependency reading a `worker_id` path/query param; raises `NotFound(code="worker_not_found")` below the minimum; carries attribute `__bonarda_visibility_guard__ = True`.
  - `unguarded_worker_routes(app) -> list[str]`.
  - `GrantService(session)`: `create(actor, data: GrantCreate) -> AccessGrant`, `revoke(actor, grant_id) -> None`, `list_active(granted_to_id) -> list[AccessGrant]`, `sweep_expired() -> int`. Error codes `grant_expiry_in_past`, `grant_too_long`, `grant_invalid_grantee`, `grant_not_found`.
  - Schemas `GrantCreate`, `GrantRead`; event `GrantCreated(aggregate_id, granted_to_id, scoped_worker_id, expires_at)` with `event_type = "identity.grant_created"`.
  - Routes `POST /api/v1/access-grants` (201), `GET /api/v1/access-grants`, `DELETE /api/v1/access-grants/{grant_id}` (204).
  - Arq cron job `expire_access_grants(ctx) -> int`, every 5 minutes.

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_visibility_policy.py`:

```python
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.identity.models import AccessGrant
from app.modules.identity.visibility import Visibility, VisibilityPolicy
from tests.support import make_user


def _actor(role: UserRole, worker_id: UUID | None = None) -> Actor:
    return Actor(user_id=uuid4(), role=role, worker_id=worker_id)


async def test_worker_sees_only_themselves(session: AsyncSession) -> None:
    me, other = uuid4(), uuid4()
    policy = VisibilityPolicy()

    assert await policy.level(session, _actor(UserRole.WORKER, me), me) is Visibility.SELF
    assert await policy.level(session, _actor(UserRole.WORKER, me), other) is Visibility.NONE


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (UserRole.PEOPLE_OPS, Visibility.DETAIL),
        (UserRole.ADMIN, Visibility.DETAIL),
        (UserRole.FINANCE, Visibility.NONE),
        (UserRole.PM, Visibility.NONE),
    ],
)
async def test_staff_defaults(session: AsyncSession, role: UserRole, expected: Visibility) -> None:
    assert await VisibilityPolicy().level(session, _actor(role), uuid4()) is expected


async def test_pm_takes_the_highest_level_from_sources(session: AsyncSession) -> None:
    async def summary(s: AsyncSession, a: Actor, w: UUID) -> Visibility:
        return Visibility.SUMMARY

    async def none(s: AsyncSession, a: Actor, w: UUID) -> Visibility:
        return Visibility.NONE

    policy = VisibilityPolicy([none, summary])

    assert await policy.level(session, _actor(UserRole.PM), uuid4()) is Visibility.SUMMARY


async def _grant(session: AsyncSession, pm_id: UUID, worker_id: UUID, **overrides: object) -> None:
    values: dict[str, object] = {
        "granted_to_id": pm_id,
        "scoped_worker_id": worker_id,
        "reason": "covering Project Volta staffing",
        "expires_at": utcnow() + timedelta(days=1),
    }
    values.update(overrides)
    session.add(AccessGrant(**values))
    await session.commit()


async def test_active_grant_gives_pm_detail(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker_id = uuid4()
    await _grant(session, pm.id, worker_id)

    level = await VisibilityPolicy().level(session, Actor(pm.id, UserRole.PM), worker_id)

    assert level is Visibility.DETAIL


@pytest.mark.parametrize(
    "overrides",
    [
        {"expires_at": utcnow() - timedelta(seconds=1)},
        {"revoked_at": utcnow() - timedelta(minutes=1)},
    ],
)
async def test_expired_or_revoked_grant_gives_nothing(
    session: AsyncSession, overrides: dict[str, object]
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker_id = uuid4()
    await _grant(session, pm.id, worker_id, **overrides)

    level = await VisibilityPolicy().level(session, Actor(pm.id, UserRole.PM), worker_id)

    assert level is Visibility.NONE
```

`backend/tests/api/test_visibility_guard.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI

from app.modules.identity.visibility import Visibility, require_visibility, unguarded_worker_routes


def test_detects_worker_routes_without_a_guard() -> None:
    app = FastAPI()

    @app.get("/workers/{worker_id}/guarded")
    async def guarded(
        level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
    ) -> None:
        return None

    @app.get("/workers/{worker_id}/leaky")
    async def leaky(worker_id: UUID) -> None:
        return None

    @app.get("/prefill")
    async def query_param_leak(worker_id: UUID) -> None:
        return None

    assert sorted(unguarded_worker_routes(app)) == ["/prefill", "/workers/{worker_id}/leaky"]


def test_application_has_no_unguarded_worker_routes(app: FastAPI) -> None:
    assert unguarded_worker_routes(app) == []
```

`backend/tests/api/identity/test_access_grants.py`:

```python
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
        "access_grant.created", ops.id, "Cross-team staffing for Project Volta"
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

    response = await client.delete(f"/api/v1/access-grants/{uuid4()}", headers=bearer(settings, ops))

    assert response.json()["code"] == "grant_not_found"


async def test_sweep_records_lapsed_grants_once(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    lapsed_at = utcnow() - timedelta(minutes=3)
    session.add_all(
        [
            AccessGrant(
                granted_to_id=pm.id, scoped_worker_id=uuid4(), reason="old cover", expires_at=lapsed_at
            ),
            AccessGrant(
                granted_to_id=pm.id, scoped_worker_id=uuid4(), reason="live cover",
                expires_at=utcnow() + timedelta(days=1),
            ),
        ]
    )
    await session.commit()

    first = await GrantService(session).sweep_expired()
    await session.commit()
    second = await GrantService(session).sweep_expired()

    assert (first, second) == (1, 0)
    expired = (await session.scalars(select(AccessGrant).where(AccessGrant.reason == "old cover"))).one()
    assert expired.revoked_at == lapsed_at
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions == ["access_grant.expired"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_visibility_policy.py tests/api/test_visibility_guard.py tests/api/identity/test_access_grants.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.identity.visibility'`.

- [ ] **Step 3: Implement**

`backend/app/modules/identity/visibility.py`:

```python
from collections.abc import Awaitable, Callable, Sequence
from enum import IntEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.enums import UserRole
from app.core.errors import NotFound
from app.core.time import utcnow
from app.modules.identity.dependencies import CurrentActor
from app.modules.identity.repository import AccessGrantRepository


class Visibility(IntEnum):
    NONE = 0
    SUMMARY = 1  # search card (spec §7.1)
    DETAIL = 2  # history, feedback, standing factors, disputes
    SELF = 3  # the worker looking at their own passport


VisibilitySource = Callable[[AsyncSession, Actor, UUID], Awaitable[Visibility]]


class VisibilityPolicy:
    """The single enforcement point for who may see which worker (FR-9.4).
    Relationship rules owned by other modules (engaged on my project,
    shortlisted for my project) plug in as sources via app.wiring."""

    def __init__(self, sources: Sequence[VisibilitySource] = ()) -> None:
        self._sources = tuple(sources)

    async def level(self, session: AsyncSession, actor: Actor, worker_id: UUID) -> Visibility:
        if actor.role is UserRole.WORKER:
            return Visibility.SELF if actor.worker_id == worker_id else Visibility.NONE
        if actor.role in (UserRole.PEOPLE_OPS, UserRole.ADMIN):
            return Visibility.DETAIL
        if actor.role is not UserRole.PM:
            return Visibility.NONE
        if await AccessGrantRepository(session).has_active(actor.user_id, worker_id, utcnow()):
            return Visibility.DETAIL
        best = Visibility.NONE
        for source in self._sources:
            best = max(best, await source(session, actor, worker_id))
            if best >= Visibility.DETAIL:
                break
        return best


def get_visibility_policy(request: Request) -> VisibilityPolicy:
    return request.app.state.visibility_policy


GUARD_MARKER = "__bonarda_visibility_guard__"


def require_visibility(minimum: Visibility) -> Callable[..., Awaitable[Visibility]]:
    """Route dependency for anything addressed by `worker_id`. Below the
    minimum it answers 404, so callers cannot probe which workers exist."""

    async def dependency(
        worker_id: UUID,
        actor: CurrentActor,
        session: SessionDep,
        policy: Annotated[VisibilityPolicy, Depends(get_visibility_policy)],
    ) -> Visibility:
        level = await policy.level(session, actor, worker_id)
        if level < minimum:
            raise NotFound("Worker not found", code="worker_not_found")
        return level

    setattr(dependency, GUARD_MARKER, True)
    return dependency


def _has_guard(dependant: Dependant) -> bool:
    return any(
        getattr(sub.call, GUARD_MARKER, False) or _has_guard(sub) for sub in dependant.dependencies
    )


def unguarded_worker_routes(app: FastAPI) -> list[str]:
    """Routes that take a `worker_id` (path or query) without require_visibility."""
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        flat = get_flat_dependant(route.dependant)
        params = {p.name for p in flat.path_params + flat.query_params}
        if "worker_id" in params and not _has_guard(route.dependant):
            offenders.append(route.path)
    return offenders
```

Append to `backend/app/modules/identity/schemas.py` (add imports `from datetime import datetime`, `from typing import ClassVar`, `from pydantic import AwareDatetime, ConfigDict, Field`, `from app.core.outbox.events import DomainEvent`):

```python
class GrantCreate(BaseModel):
    granted_to_id: UUID
    scoped_worker_id: UUID
    reason: str = Field(min_length=10, max_length=500)
    expires_at: AwareDatetime


class GrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    granted_to_id: UUID
    scoped_worker_id: UUID
    granted_by_id: UUID | None
    reason: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class GrantCreated(DomainEvent):
    event_type: ClassVar[str] = "identity.grant_created"
    granted_to_id: UUID
    scoped_worker_id: UUID
    expires_at: datetime
```

`backend/app/modules/identity/grants.py`:

```python
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.enums import AccountStatus, UserRole
from app.core.errors import BadRequest, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import AccessGrant
from app.modules.identity.repository import AccessGrantRepository, UserRepository
from app.modules.identity.schemas import GrantCreate, GrantCreated, GrantRead

MAX_GRANT_DURATION = timedelta(days=90)


class GrantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.grants = AccessGrantRepository(session)
        self.users = UserRepository(session)

    async def create(self, actor: Actor, data: GrantCreate) -> AccessGrant:
        now = utcnow()
        if data.expires_at <= now:
            raise BadRequest("Expiry must be in the future", code="grant_expiry_in_past")
        if data.expires_at > now + MAX_GRANT_DURATION:
            raise BadRequest("Grants may last at most 90 days", code="grant_too_long")
        grantee = await self.users.get(data.granted_to_id)
        if grantee is None or grantee.role is not UserRole.PM or grantee.status is not AccountStatus.ACTIVE:
            raise BadRequest("Grants can only be given to active PMs", code="grant_invalid_grantee")
        grant = self.grants.add(
            AccessGrant(
                granted_to_id=data.granted_to_id,
                scoped_worker_id=data.scoped_worker_id,
                granted_by_id=actor.user_id,
                reason=data.reason,
                expires_at=data.expires_at,
            )
        )
        await self.session.flush()
        await write_audit(
            self.session,
            actor=actor,
            action="access_grant.created",
            target_type="access_grant",
            target_id=grant.id,
            after=GrantRead.model_validate(grant).model_dump(mode="json"),
            reason=data.reason,
        )
        await emit_event(
            self.session,
            GrantCreated(
                aggregate_id=grant.id,
                granted_to_id=grant.granted_to_id,
                scoped_worker_id=grant.scoped_worker_id,
                expires_at=grant.expires_at,
            ),
        )
        return grant

    async def revoke(self, actor: Actor, grant_id: UUID) -> None:
        grant = await self.grants.get(grant_id)
        if grant is None:
            raise NotFound("Access grant not found", code="grant_not_found")
        if grant.revoked_at is not None:
            return
        grant.revoked_at = utcnow()
        await write_audit(
            self.session,
            actor=actor,
            action="access_grant.revoked",
            target_type="access_grant",
            target_id=grant.id,
            before={"revoked_at": None},
            after={"revoked_at": grant.revoked_at.isoformat()},
        )

    async def list_active(self, granted_to_id: UUID | None) -> list[AccessGrant]:
        return await self.grants.list_active(granted_to_id=granted_to_id, at=utcnow())

    async def sweep_expired(self) -> int:
        """Records each lapsed grant once. Access already stopped at expires_at;
        this only makes the lapse visible in the audit trail (NFR-3.8)."""
        lapsed = await self.grants.list_lapsed(utcnow())
        for grant in lapsed:
            grant.revoked_at = grant.expires_at
            await write_audit(
                self.session,
                actor=None,
                action="access_grant.expired",
                target_type="access_grant",
                target_id=grant.id,
                before={"revoked_at": None},
                after={"revoked_at": grant.expires_at.isoformat()},
            )
        return len(lapsed)
```

Add to `backend/app/modules/identity/router.py` — imports (`Actor` is already imported from Task 8):

```python
from uuid import UUID

from app.modules.identity.dependencies import require_permission
from app.modules.identity.grants import GrantService
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import GrantCreate, GrantRead
```

and routes:

```python
GrantManager = Annotated[Actor, Depends(require_permission(Permission.ACCESS_GRANT_MANAGE))]


@router.post("/access-grants", status_code=201)
async def create_access_grant(
    body: GrantCreate, actor: GrantManager, session: SessionDep
) -> GrantRead:
    grant = await GrantService(session).create(actor, body)
    return GrantRead.model_validate(grant)


@router.get("/access-grants")
async def list_access_grants(
    actor: GrantManager, session: SessionDep, granted_to_id: UUID | None = None
) -> list[GrantRead]:
    grants = await GrantService(session).list_active(granted_to_id)
    return [GrantRead.model_validate(g) for g in grants]


@router.delete("/access-grants/{grant_id}", status_code=204)
async def revoke_access_grant(grant_id: UUID, actor: GrantManager, session: SessionDep) -> None:
    await GrantService(session).revoke(actor, grant_id)
```

Replace `backend/app/modules/identity/service.py` with:

```python
"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.dependencies import CurrentActor, require_permission
from app.modules.identity.permissions import Permission
from app.modules.identity.visibility import (
    Visibility,
    VisibilityPolicy,
    VisibilitySource,
    require_visibility,
)

__all__ = [
    "CurrentActor",
    "Permission",
    "Visibility",
    "VisibilityPolicy",
    "VisibilitySource",
    "require_permission",
    "require_visibility",
]
```

Replace `backend/app/wiring.py` with:

```python
"""Composition root: the only place that knows every module's handlers and
visibility sources. Later plans register theirs here."""

from app.core.outbox.registry import HandlerRegistry
from app.modules.identity.service import VisibilitySource


def build_registry() -> HandlerRegistry:
    return HandlerRegistry()


def visibility_sources() -> list[VisibilitySource]:
    return []
```

In `backend/app/main.py` add imports `from app.modules.identity.service import VisibilityPolicy` and `from app.wiring import visibility_sources`, and after the OIDC provider line:

```python
    app.state.visibility_policy = VisibilityPolicy(visibility_sources())
```

Append to `backend/app/worker/jobs.py` (add `from app.modules.identity.grants import GrantService`):

```python
async def expire_access_grants(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await GrantService(session).sweep_expired()
```

In `backend/app/worker/settings.py` import `expire_access_grants` and replace `cron_jobs` with:

```python
    cron_jobs: ClassVar[list[Any]] = [
        cron(purge_outbox, hour={2}, minute={30}),
        cron(expire_access_grants, minute=set(range(0, 60, 5))),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_visibility_policy.py tests/api/test_visibility_guard.py tests/api/identity/test_access_grants.py -v`
Expected: 20 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(identity): visibility policy, route guard check and access grants

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: SCIM deactivation and role changes

**Files:**
- Create: `backend/app/modules/identity/scim.py`
- Modify: `backend/app/modules/identity/schemas.py`, `backend/app/modules/identity/router.py`
- Test: `backend/tests/api/identity/test_scim.py`

**Interfaces:**
- Consumes: `UserRepository`, `RefreshSessionRepository`, `mark_revoked`, `write_audit`, `emit_event`, `SessionService` (in tests).
- Produces:
  - Schemas `ScimOperation(op, path, value)`, `ScimPatch(schemas, operations alias "Operations")`; event `AccessRevoked(aggregate_id, reason: Literal["deactivated", "role_changed"])` with `event_type = "identity.access_revoked"`.
  - `ScimService(session, redis, settings)`: `patch_user(subject: str, patch: ScimPatch) -> UserAccount`. Error codes `scim_user_not_found`, `scim_invalid_value`, `scim_unauthorized`.
  - Route `PATCH /api/v1/scim/v2/Users/{subject}` authenticated by `Authorization: Bearer <SCIM_BEARER_TOKEN>`; returns `application/scim+json`.

SCIM `id` is the IdP subject (`oidc_subject`). Plan 2 registers an `AccessRevoked` handler that ends the user's `project_staff` rows.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/identity/test_scim.py`:

```python
from typing import Any

import pytest
from fakeredis import aioredis as fake_aioredis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.identity.models import RefreshSession, UserAccount
from app.modules.identity.sessions import SessionService
from tests.support import bearer, make_user

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
    revoked = await session.get(UserAccount, user.id)
    assert revoked is not None
    assert revoked.status is AccountStatus.REVOKED
    sessions = (await session.scalars(select(RefreshSession))).all()
    assert all(s.revoked_at is not None for s in sessions)
    assert await redis.get(f"revoked_after:{user.id}") is not None
    audit = (await session.scalars(select(AuditLog).where(AuditLog.action == "access.revoked"))).one()
    assert audit.after == {"status": "revoked", "role": "pm"}
    event = (await session.scalars(select(OutboxEvent))).one()
    assert (event.event_type, event.payload["reason"]) == ("identity.access_revoked", "deactivated")
    me = await client.get("/api/v1/me", headers=live_token)
    assert me.json()["code"] == "session_revoked"


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
    revoked = await session.get(UserAccount, user.id)
    assert revoked is not None
    assert revoked.status is AccountStatus.REVOKED


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
    updated = await session.get(UserAccount, user.id)
    assert updated is not None
    assert (updated.role, updated.status) == (UserRole.FINANCE, AccountStatus.ACTIVE)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/identity/test_scim.py -v`
Expected: FAIL — 404 responses (route does not exist), e.g. `assert 404 == 200`.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/identity/schemas.py` (add `Any` to the typing import):

```python
class ScimOperation(BaseModel):
    op: str
    path: str | None = None
    value: Any = None


class ScimPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schemas: list[str]
    operations: list[ScimOperation] = Field(alias="Operations")


class AccessRevoked(DomainEvent):
    event_type: ClassVar[str] = "identity.access_revoked"
    reason: Literal["deactivated", "role_changed"]
```

`backend/app/modules/identity/scim.py`:

```python
from dataclasses import dataclass
from typing import Any, Literal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.errors import BadRequest, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import RefreshSessionRepository, UserRepository
from app.modules.identity.revocation import mark_revoked
from app.modules.identity.schemas import AccessRevoked, ScimPatch


@dataclass
class _Changes:
    active: bool | None = None
    role: UserRole | None = None


def _invalid(detail: str) -> BadRequest:
    return BadRequest(detail, code="scim_invalid_value")


def _parse_bool(value: Any) -> bool:
    # bool("False") is True — IdPs such as Azure AD send booleans as strings.
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise _invalid("'active' must be a boolean")


def _parse_role(value: Any) -> UserRole:
    try:
        return UserRole(value[0]["value"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise _invalid("'roles' must be a list like [{\"value\": \"pm\"}]") from exc


def _interpret(patch: ScimPatch) -> _Changes:
    changes = _Changes()
    for operation in patch.operations:
        if operation.op.lower() not in ("replace", "add"):
            continue
        if operation.path == "active":
            changes.active = _parse_bool(operation.value)
        elif operation.path == "roles":
            changes.role = _parse_role(operation.value)
        elif operation.path is None and isinstance(operation.value, dict):
            if "active" in operation.value:
                changes.active = _parse_bool(operation.value["active"])
            if "roles" in operation.value:
                changes.role = _parse_role(operation.value["roles"])
    return changes


class ScimService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.users = UserRepository(session)
        self.refresh = RefreshSessionRepository(session)

    async def patch_user(self, subject: str, patch: ScimPatch) -> UserAccount:
        user = await self.users.get_by_oidc_subject(subject)
        if user is None:
            raise NotFound("No account for this SCIM id", code="scim_user_not_found")
        changes = _interpret(patch)
        before = {"status": user.status.value, "role": user.role.value}
        reason: Literal["deactivated", "role_changed"] | None = None

        if changes.active is False and user.status is AccountStatus.ACTIVE:
            user.status = AccountStatus.REVOKED
            reason = "deactivated"
        elif changes.active is True and user.status is AccountStatus.REVOKED:
            user.status = AccountStatus.ACTIVE
            await write_audit(
                self.session,
                actor=None,
                action="user.reactivated",
                target_type="user_account",
                target_id=user.id,
                before=before,
                after={"status": user.status.value, "role": user.role.value},
                reason="scim",
            )
        if changes.role is not None and changes.role is not user.role:
            user.role = changes.role
            if reason is None:
                reason = "role_changed"

        if reason is not None:
            await self._revoke(user, before, reason)
        return user

    async def _revoke(
        self,
        user: UserAccount,
        before: dict[str, str],
        reason: Literal["deactivated", "role_changed"],
    ) -> None:
        now = utcnow()
        await self.refresh.revoke_all_for_user(user.id, now)
        await mark_revoked(self.redis, self.settings, user.id, now)
        await write_audit(
            self.session,
            actor=None,
            action="access.revoked",
            target_type="user_account",
            target_id=user.id,
            before=before,
            after={"status": user.status.value, "role": user.role.value},
            reason=reason,
        )
        await emit_event(self.session, AccessRevoked(aggregate_id=user.id, reason=reason))
```

Add to `backend/app/modules/identity/router.py` — imports:

```python
import secrets

from fastapi import Header
from fastapi.responses import JSONResponse

from app.modules.identity.schemas import ScimPatch
from app.modules.identity.scim import ScimService
```

and code:

```python
async def require_scim_token(
    settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
) -> None:
    expected = f"Bearer {settings.scim_bearer_token.get_secret_value()}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise Unauthorized("Invalid SCIM credentials", code="scim_unauthorized")


@router.patch("/scim/v2/Users/{subject}", dependencies=[Depends(require_scim_token)])
async def scim_patch_user(
    subject: str, body: ScimPatch, session: SessionDep, redis: RedisDep, settings: SettingsDep
) -> JSONResponse:
    user = await ScimService(session, redis, settings).patch_user(subject, body)
    return JSONResponse(
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": subject,
            "userName": user.email,
            "active": user.status.value == "active",
        },
        media_type="application/scim+json",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/identity/test_scim.py -v`
Expected: 9 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(identity): SCIM deactivation and role changes with immediate revocation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Module boundary check, CI pipeline, documentation

**Files:**
- Create: `backend/tests/unit/test_module_boundaries.py`, `.github/workflows/ci.yml`
- Modify: `PROJECT_STRUCTURE.md`

**Interfaces:**
- Consumes: the whole backend.
- Produces: `find_boundary_violations(modules_root: Path) -> list[str]` (in the test module); a CI workflow running every check from the Global Constraints.

- [ ] **Step 1: Write the boundary test**

`backend/tests/unit/test_module_boundaries.py`:

```python
"""Boundary rule 1 (spec §5.2): a module may import another module only through
its `service` or `schemas` submodule. import-linter covers the layering rules;
this test covers the per-module public-interface rule."""

import ast
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"
PUBLIC_SUBMODULES = {"service", "schemas"}


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        if len(node.module.split(".")) == 3:  # from app.modules.x import y
            return [f"{node.module}.{alias.name}" for alias in node.names]
        return [node.module]
    return []


def find_boundary_violations(modules_root: Path) -> list[str]:
    violations = []
    for path in sorted(modules_root.rglob("*.py")):
        own_module = path.relative_to(modules_root).parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for name in _imported_names(node):
                parts = name.split(".")
                if parts[:2] != ["app", "modules"] or len(parts) < 3 or parts[2] == own_module:
                    continue
                if len(parts) == 3 or parts[3] not in PUBLIC_SUBMODULES:
                    violations.append(f"{path.relative_to(modules_root)}: imports {name}")
    return violations


def test_checker_catches_private_imports(tmp_path: Path) -> None:
    (tmp_path / "roster").mkdir()
    (tmp_path / "roster" / "ok.py").write_text(
        "from app.modules.identity.service import CurrentActor\n"
        "from app.modules.identity import schemas\n"
        "from app.modules.roster.models import X\n"
    )
    (tmp_path / "roster" / "bad.py").write_text(
        "from app.modules.identity.models import UserAccount\n"
        "from app.modules.identity import repository\n"
        "import app.modules.identity\n"
    )

    assert find_boundary_violations(tmp_path) == [
        "roster/bad.py: imports app.modules.identity.models",
        "roster/bad.py: imports app.modules.identity.repository",
        "roster/bad.py: imports app.modules.identity",
    ]


def test_application_modules_respect_boundaries() -> None:
    assert find_boundary_violations(MODULES_ROOT) == []
```

Run: `pytest tests/unit/test_module_boundaries.py -v`
Expected: 2 passed. (On Windows the tmp-path test compares POSIX-style paths; if it fails only on separators, change the f-string to `path.relative_to(modules_root).as_posix()`.)

- [ ] **Step 2: Add the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements*.txt
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff format --check .
      - run: ruff check .
      - run: mypy
      - run: lint-imports
      - run: pytest --cov=app --cov-report=term-missing
```

- [ ] **Step 3: Update PROJECT_STRUCTURE.md to match what was built**

In `PROJECT_STRUCTURE.md` §5.1, replace the two run commands:

```bash
uvicorn app.main:app --reload --port 8000
arq app.worker.settings.WorkerSettings    # second terminal: relay, handlers, cron
```

with:

```bash
uvicorn app.main:create_app --factory --reload --port 8000
arq app.worker.settings.WorkerSettings    # second terminal: relay, handlers, cron
```

In the same file's §2 "Design notes", append this bullet:

```markdown
- **Composition root.** `app/main.py` (API), `app/worker/` (Arq) and `app/wiring.py` (event handler registry and visibility sources) are the only places that know about every module. Modules never import them (import-linter), and `tests/unit/test_module_boundaries.py` enforces that modules use each other only through `service` and `schemas`. Staff OIDC lives in `modules/identity/oidc.py` rather than `integrations/`, because identity is its only user.
```

In §1's tree, under `app/`, add the line `│   │   ├── wiring.py                      # handler registry + visibility sources (composition root)` directly below the `main.py` line.

- [ ] **Step 4: Run the full verification**

Run: `ruff format --check . && ruff check . && mypy && lint-imports && pytest --cov=app --cov-report=term-missing`
Expected: all pass; 115 tests; coverage report printed. Record the actual test count and coverage in the commit body.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/tests .github PROJECT_STRUCTURE.md
git commit -m "chore: enforce module boundaries and add backend CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage for this plan

| Spec item | Task |
|---|---|
| §5.2 boundary rules 1–3 | 1 (import-linter), 3 (same-session writers), 12 (public-interface test) |
| §5.3 transactional outbox, relay, handler dedupe, purge | 3, 4 |
| §5.2 rule 5 / Risk 1 — visibility dependency on every worker route | 10 (`require_visibility`, `unguarded_worker_routes` test) |
| §6.3 append-only audit log, retention-role exception | 1 (trigger), 3 (tests) |
| §7.1 roles and visibility levels | 9, 10 |
| §7.2 identity endpoints | 6, 7, 8, 10, 11 |
| §7.6 revocation sequence | 5, 11 |
| §7.7 dead-letter after 5 tries; `expire_access_grants`; `purge_outbox` | 4, 10 |
| §8.1 tokens, refresh rotation, reuse detection, MFA check, magic links, rate limits, fail-open revocation | 5–8 |
| §8.3 correlation IDs through the outbox | 2, 3, 4 |
| RFC 9457 errors | 2 |
| NFR-8.1 no hard-coded English in sent email | 7 |

Deferred to later plans by design: `passport`/`engagements`/`integrations` (Plan 2), `policy_configs`/`standing`/`roster` (Plan 3), governance and the `can_view_governance` check (Plan 4), frontend (Plan 5), SMTP mailer, Keycloak verification of `AuthlibOidcProvider`, and Prometheus metrics (Plan 6).

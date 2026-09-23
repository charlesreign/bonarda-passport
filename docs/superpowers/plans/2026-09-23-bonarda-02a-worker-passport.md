# Bonarda Plan 2A — Worker Passport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `passport` module (workers, skills taxonomy and claims, profile read/update, onboarding, consents, PM invitations), a real SMTP mailer with mail sent from the outbox worker instead of the request path, per-account locale, and the Plan 1 carry-forward identity fixes.

**Architecture:** Builds on Plan 1's modular monolith (branch `feat/backend-foundation`). `passport` is a new domain module under `app/modules/passport/` with its own router/services/repositories/models/schemas, and a `service.py` facade. `integrations` starts with the SMTP mailer. Outbox handlers now receive their dependencies (Redis, settings, mailer) through a `HandlerDeps` object built in the composition root (`app/wiring.py`), so side effects like email run in the Arq worker. Workers are always addressed in URL paths, never in request bodies, so the Plan 1 visibility-guard CI check covers every worker route.

**Tech Stack:** Python 3.12, FastAPI 0.115 (pinned), Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis, Arq, aiosmtplib 3.0.2, pytest + Testcontainers + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md` (§5 modules, §6 data, §7.1–7.2 visibility and API, §8.1 security). Roadmap and carry-forward table: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`. Plan 2B (engagements and reactivation) is written after this plan lands.

## Global Constraints

- Work on top of branch `feat/backend-foundation` (Plan 1). All commands run from `backend/` with the venv at `backend/.venv` activated (`source .venv/Scripts/activate` in Git Bash). Docker must be running (Testcontainers Postgres).
- All routes are under `/api/v1`. Errors are RFC 9457 `application/problem+json` with a stable `code` field.
- A module imports another module only through its `service` or `schemas` submodule. `app/main.py`, `app/worker/` and `app/wiring.py` are the composition root and may import anything. `app.core` imports no module.
- Every state change of administrative, security or privacy significance writes `write_audit(...)` on the request's `AsyncSession`; every change other modules must react to emits `emit_event(...)` on the same session. Request code never enqueues Arq jobs and never sends email directly.
- Workers are addressed in URL paths (`/workers/{worker_id}/…` or `/workers/me/…`). A request body must never carry a `worker_id` field (Task 9 makes CI enforce this).
- Enum columns use `app.core.db.types.pg_enum` (stores lowercase values).
- In Alembic migrations, any check constraint name must be passed through `op.f("ck_<table>_<name>")` (the naming convention `ck_%(table_name)s_%(constraint_name)s` otherwise prefixes it twice). Unique, foreign-key and primary-key names are passed as plain strings.
- Datetimes are timezone-aware UTC (`app.core.time.utcnow()`); dates use `datetime.date`.
- User-facing email text comes from `app.core.i18n` in English and French.
- Async tests never call `session.expire_all()` followed by `session.get(...)` (raises `MissingGreenlet`); use `await session.refresh(obj)`.
- Before every commit: `ruff format . && ruff check . && mypy && lint-imports && pytest` — all must pass.
- Commit messages end with a `Co-Authored-By:` trailer naming the model that wrote the commit.

## Review Focus

1. **Inviting an email that already belongs to any account** (a staff member, or a worker already invited) must return `409 email_in_use` and leave no orphan `workers` row. (Test in Task 8.)
2. **Languages sent with duplicates or wrong case** (`["en", "fr", "en"]`, `["EN"]`) must be de-duplicated preserving order, or rejected with 422 — never stored as-is. (Test in Task 6.)
3. **Skill search terms containing SQL wildcards** (`%`, `_`) must match literally, not as patterns. (Test in Task 5.)
4. **A worker deactivated between requesting a sign-in link and the worker process sending it** must not receive a link. (Test in Task 2.)
5. **A consent toggled to the value it already has** must not create an audit row or an event. (Test in Task 7.)

---

## File Structure

```
backend/
  requirements.txt                               + aiosmtplib (Task 1)
  alembic/versions/0004_user_locale.py           user_accounts.locale (Task 2)
  alembic/versions/0005_passport.py              workers, skills, skill_claims, consents, FKs (Task 4)
  app/
    main.py                                      mailer via build_mailer; passport router; models registry import
    wiring.py                                    HandlerDeps, build_registry(deps)
    models_registry.py                           + passport models
    core/config.py                               + smtp_url, mail_from
    core/i18n.py                                 + Locale, SUPPORTED_LOCALES, invitation templates
    worker/settings.py                           builds HandlerDeps (handler Redis client, mailer)
    modules/integrations/
      __init__.py
      smtp.py                                    SmtpMailer
      service.py                                 build_mailer(settings) — public facade
    modules/identity/
      models.py                                  + UserAccount.locale; FKs to workers
      schemas.py                                 + MeUpdate, AccountContact, SignInPurpose, MagicLinkRequested
      accounts.py                                account_contact, provision_worker_account, request_sign_in_link
      magic_link.py                              request emits event; send_magic_link() for the worker
      handlers.py                                register(registry, …) — identity.send_magic_link
      scim.py, oidc_login.py, grants.py          carry-forward fixes (Tasks 3, 4)
      visibility.py                              body worker_id check (Task 9)
      permissions.py                             + SKILL_MANAGE (Task 5)
      router.py                                  PATCH /me; magic-link routes without mailer
      service.py                                 + accounts exports
    modules/passport/
      __init__.py
      enums.py                                   WorkerType, WorkerStatus, OnboardingState, …
      models.py                                  Worker, Skill, SkillClaim, Consent
      repository.py                              WorkerRepository, SkillRepository, SkillClaimRepository, ConsentRepository
      schemas.py                                 request/response models, events
      dependencies.py                            WorkerActor, WorkerReader, WorkerEditor
      skills.py                                  SkillService, ClaimService
      profile.py                                 ProfileService
      consents.py                                ConsentService
      invitations.py                             InvitationService
      router.py                                  all passport routes
      service.py                                 public facade
  tests/
    support.py                                   + RecordingMailer, drain_outbox, make_worker
    conftest.py                                  + mailer, drain fixtures
    unit/integrations/test_smtp.py, test_build_mailer.py
    integration/test_passport_schema.py
    api/identity/test_me.py
    api/passport/test_skills.py, test_worker_profile.py, test_consents.py, test_invitations.py
docs/permissions.md                              regenerated (Task 5)
docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md   Plan 2 split into 2A/2B (Task 9)
```

---

### Task 1: SMTP mailer and `build_mailer`

**Files:**
- Modify: `backend/requirements.txt`, `backend/app/core/config.py`, `backend/app/main.py`
- Create: `backend/app/modules/integrations/__init__.py`, `backend/app/modules/integrations/smtp.py`, `backend/app/modules/integrations/service.py`
- Test: `backend/tests/unit/integrations/__init__.py`, `backend/tests/unit/integrations/test_smtp.py`, `backend/tests/unit/integrations/test_build_mailer.py`

**Interfaces:**
- Consumes: `Mailer` protocol and `ConsoleMailer` from `app.core.mail`; `Settings`.
- Produces: `Settings.smtp_url: SecretStr | None`, `Settings.mail_from: str`; `SmtpMailer(url: str, sender: str)` with `async send(*, to, subject, body) -> None`; `build_mailer(settings) -> Mailer` (exported from `app.modules.integrations.service`). `create_app` uses `build_mailer` when no mailer is passed.

- [ ] **Step 1: Add the dependency and settings**

Append to `backend/requirements.txt` under a new heading, then install:

```text
# --- Email ---
aiosmtplib==3.0.2
```

```bash
pip install aiosmtplib==3.0.2
```

In `backend/app/core/config.py`, add these fields to `Settings` directly after `scim_bearer_token: SecretStr`:

```python
    # smtp://user:pass@host:port (STARTTLS when offered) or smtps://… (implicit TLS).
    # Unset in dev/test means mail is written to the log instead.
    smtp_url: SecretStr | None = None
    mail_from: str = "Bonarda Works <no-reply@bonarda.works>"
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/unit/integrations/__init__.py`: empty file.

`backend/tests/unit/integrations/test_smtp.py`:

```python
from typing import Any

import pytest

from app.modules.integrations import smtp
from app.modules.integrations.smtp import SmtpMailer


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []

    async def fake_send(message: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        calls.append((message, kwargs))
        return {}, "OK"

    monkeypatch.setattr(smtp.aiosmtplib, "send", fake_send)
    return calls


async def test_sends_plain_text_message_with_headers(
    sent: list[tuple[Any, dict[str, Any]]],
) -> None:
    mailer = SmtpMailer("smtp://mailpit:1025", "Bonarda <no-reply@bonarda.works>")

    await mailer.send(to="kofi@example.com", subject="Hello", body="Body text")

    message, kwargs = sent[0]
    assert message["From"] == "Bonarda <no-reply@bonarda.works>"
    assert message["To"] == "kofi@example.com"
    assert message["Subject"] == "Hello"
    assert message.get_content().strip() == "Body text"
    assert (kwargs["hostname"], kwargs["port"], kwargs["use_tls"]) == ("mailpit", 1025, False)
    assert kwargs["username"] is None
    assert kwargs["password"] is None


async def test_smtps_url_uses_implicit_tls_default_port_and_decoded_credentials(
    sent: list[tuple[Any, dict[str, Any]]],
) -> None:
    mailer = SmtpMailer("smtps://apikey:p%40ss@smtp.example.com", "no-reply@bonarda.works")

    await mailer.send(to="a@b.c", subject="s", body="b")

    kwargs = sent[0][1]
    assert (kwargs["hostname"], kwargs["port"], kwargs["use_tls"]) == ("smtp.example.com", 465, True)
    assert (kwargs["username"], kwargs["password"]) == ("apikey", "p@ss")


@pytest.mark.parametrize("url", ["http://mail.example.com", "smtp://"])
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError, match="smtp_url"):
        SmtpMailer(url, "no-reply@bonarda.works")
```

`backend/tests/unit/integrations/test_build_mailer.py`:

```python
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.mail import ConsoleMailer
from app.modules.integrations.service import SmtpMailer, build_mailer


def test_smtp_url_gives_smtp_mailer(settings: Settings) -> None:
    configured = settings.model_copy(update={"smtp_url": SecretStr("smtp://mailpit:1025")})

    assert isinstance(build_mailer(configured), SmtpMailer)


def test_dev_and_test_without_smtp_log_to_console(settings: Settings) -> None:
    assert isinstance(build_mailer(settings), ConsoleMailer)
    assert isinstance(build_mailer(settings.model_copy(update={"env": "dev"})), ConsoleMailer)


def test_production_without_smtp_refuses_to_start(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="mailer"):
        build_mailer(settings.model_copy(update={"env": "prod"}))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/integrations -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.integrations'`.

- [ ] **Step 4: Implement**

`backend/app/modules/integrations/__init__.py`: empty file.

`backend/app/modules/integrations/smtp.py`:

```python
from email.message import EmailMessage
from urllib.parse import unquote, urlsplit

import aiosmtplib

SMTP_TIMEOUT_SECONDS = 10.0


class SmtpMailer:
    """Sends plain-text mail over SMTP. `smtps://` means implicit TLS (default
    port 465); `smtp://` upgrades with STARTTLS when the server offers it."""

    def __init__(self, url: str, sender: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("smtp", "smtps"):
            raise ValueError("smtp_url must start with smtp:// or smtps://")
        if not parts.hostname:
            raise ValueError("smtp_url must include a host")
        self._implicit_tls = parts.scheme == "smtps"
        self._host = parts.hostname
        self._port = parts.port or (465 if self._implicit_tls else 25)
        self._username = unquote(parts.username) if parts.username else None
        self._password = unquote(parts.password) if parts.password else None
        self._sender = sender

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await aiosmtplib.send(
            message,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._implicit_tls,
            timeout=SMTP_TIMEOUT_SECONDS,
        )
```

`backend/app/modules/integrations/service.py`:

```python
"""Public interface of the integrations module."""

from app.core.config import Settings
from app.core.mail import ConsoleMailer, Mailer
from app.modules.integrations.smtp import SmtpMailer

NON_PRODUCTION_ENVS = frozenset({"dev", "test"})


def build_mailer(settings: Settings) -> Mailer:
    if settings.smtp_url is not None:
        return SmtpMailer(settings.smtp_url.get_secret_value(), settings.mail_from)
    if settings.env in NON_PRODUCTION_ENVS:
        # ConsoleMailer logs full sign-in links: acceptable only on a
        # developer's own machine or in tests.
        return ConsoleMailer()
    raise RuntimeError("A real mailer must be configured outside dev/test: set SMTP_URL")


__all__ = ["SmtpMailer", "build_mailer"]
```

In `backend/app/main.py`, replace the whole `if mailer is None:` block (the one raising "A real mailer must be configured outside dev/test") with:

```python
    mailer = mailer or build_mailer(settings)
```

and add the import `from app.modules.integrations.service import build_mailer`. Remove the now-unused `ConsoleMailer` import from `main.py` (keep `Mailer`).

If mypy reports missing type information for `aiosmtplib`, add `"aiosmtplib.*"` to the `ignore_missing_imports` module list in `backend/pyproject.toml`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/integrations tests/unit/test_config.py -v`
Expected: all pass (5 new tests plus the existing config tests, including the one expecting `RuntimeError` matching "mailer").

- [ ] **Step 6: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add requirements.txt pyproject.toml app tests
git commit -m "feat(integrations): SMTP mailer selected by build_mailer"
```

(Append your `Co-Authored-By:` trailer to every commit message in this plan.)

---

### Task 2: Account locale and sign-in links sent from the worker

**Files:**
- Create: `backend/alembic/versions/0004_user_locale.py`, `backend/app/modules/identity/accounts.py`, `backend/app/modules/identity/handlers.py`
- Modify: `backend/app/core/i18n.py`, `backend/app/modules/identity/models.py`, `backend/app/modules/identity/schemas.py`, `backend/app/modules/identity/magic_link.py`, `backend/app/modules/identity/router.py`, `backend/app/modules/identity/service.py`, `backend/app/wiring.py`, `backend/app/worker/settings.py`
- Modify tests: `backend/tests/support.py`, `backend/tests/conftest.py`, `backend/tests/api/identity/test_magic_link.py`, `backend/tests/unit/test_i18n.py`
- Test: `backend/tests/api/identity/test_me.py`

**Interfaces:**
- Consumes: `build_mailer` (Task 1); `process_event`, `HandlerRegistry`, `emit_event`, `OutboxEvent`.
- Produces:
  - `app.core.i18n.Locale = Literal["en", "fr"]`, `SUPPORTED_LOCALES: tuple[str, ...] = ("en", "fr")`.
  - `UserAccount.locale: str` (default `"en"`, check constraint `ck_user_accounts_locale_supported`).
  - Schemas: `MeResponse.locale: str`; `MeUpdate(locale: Locale)`; `SignInPurpose = Literal["sign_in"]` (Task 8 adds `"invitation"`); `MagicLinkRequested(DomainEvent)` with `event_type = "identity.magic_link_requested"`, field `purpose: SignInPurpose = "sign_in"`; `AccountContact(email: str, locale: str)`.
  - `accounts.request_sign_in_link(session, user_id, *, purpose) -> None`; `accounts.account_contact(session, user_id) -> AccountContact`.
  - `MagicLinkService(session, redis, settings)` (no mailer) — `request()` now emits `MagicLinkRequested` instead of mailing.
  - `send_magic_link(session, *, redis, settings, mailer, user_id, purpose) -> bool` — runs in the worker.
  - `identity.handlers.register(registry, *, redis, settings, mailer)` registers handler `"identity.send_magic_link"`.
  - `app.wiring.HandlerDeps(settings, redis, mailer)`; `build_registry(deps: HandlerDeps) -> HandlerRegistry`.
  - Route `PATCH /api/v1/me` body `MeUpdate` → `MeResponse`.
  - Test helpers: `RecordingMailer` (with `.sent`, `.token()`), `drain_outbox(sessionmaker, registry)`; fixtures `mailer`, `drain`.

- [ ] **Step 1: Locale in i18n, model and migration**

In `backend/app/core/i18n.py`, add below the module docstring (before `MESSAGES`):

```python
from typing import Literal

Locale = Literal["en", "fr"]
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "fr")
```

In `backend/app/modules/identity/models.py`, add to `UserAccount` after `last_login_at`:

```python
    # Language for everything the platform sends this person (NFR-8.1/8.2).
    locale: Mapped[str] = mapped_column(
        String(5), default="en", server_default="en", nullable=False
    )

    __table_args__ = (CheckConstraint("locale IN ('en','fr')", name="locale_supported"),)
```

`backend/alembic/versions/0004_user_locale.py`:

```python
"""user_accounts.locale: language for mail and UI defaults

Revision ID: 0004_user_locale
Revises: 0003_refresh_revoked_reason
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_user_locale"
down_revision: str | None = "0003_refresh_revoked_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("locale", sa.String(5), server_default="en", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_locale_supported"), "user_accounts", "locale IN ('en','fr')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_user_accounts_locale_supported"), "user_accounts", type_="check")
    op.drop_column("user_accounts", "locale")
```

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all pass (models, check-constraint names and round-trip agree).

- [ ] **Step 2: Test helpers for mail and the outbox**

Add to `backend/tests/support.py` (merge imports at the top; `ruff check --fix` sorts them):

```python
import re
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.outbox.models import OutboxEvent
from app.core.outbox.processing import process_event
from app.core.outbox.registry import HandlerRegistry
from app.core.time import utcnow


@dataclass
class RecordingMailer:
    sent: list[dict[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})

    def token(self) -> str:
        match = re.search(r"token=([A-Za-z0-9_-]+)", self.sent[-1]["body"])
        assert match is not None
        return match.group(1)


async def drain_outbox(
    sessionmaker: async_sessionmaker[AsyncSession], registry: HandlerRegistry, *, max_rounds: int = 10
) -> None:
    """Test stand-in for the relay + Arq worker: runs every pending event's
    handlers in-process (including events those handlers emit) until the
    outbox is empty. Handler exceptions propagate to the test."""
    for _ in range(max_rounds):
        async with sessionmaker() as s:
            events = (
                await s.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.dispatched_at.is_(None))
                    .order_by(OutboxEvent.id)
                )
            ).all()
        if not events:
            return
        for event in events:
            for name in registry.handler_names_for(event.event_type):
                await process_event(sessionmaker, registry, event.event_id, name)
            async with sessionmaker() as s, s.begin():
                await s.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == event.id)
                    .values(dispatched_at=utcnow())
                )
    raise AssertionError("outbox did not drain")
```

Add to `backend/tests/conftest.py` (imports: `from collections.abc import Awaitable, Callable`, `from app.wiring import HandlerDeps, build_registry`, `from tests.support import RecordingMailer, alembic_config, drain_outbox`):

```python
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
```

- [ ] **Step 3: Write the failing tests**

Replace `backend/tests/api/identity/test_magic_link.py` with:

```python
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
```

`backend/tests/api/identity/test_me.py`:

```python
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from tests.support import bearer, make_user


async def test_me_reports_locale(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)

    response = await client.get("/api/v1/me", headers=bearer(settings, user))

    assert response.json()["locale"] == "en"


async def test_user_can_change_their_locale(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.WORKER)

    response = await client.patch(
        "/api/v1/me", json={"locale": "fr"}, headers=bearer(settings, user)
    )

    assert response.status_code == 200
    assert response.json()["locale"] == "fr"
    await session.refresh(user)
    assert user.locale == "fr"


async def test_unsupported_locale_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)

    response = await client.patch(
        "/api/v1/me", json={"locale": "de"}, headers=bearer(settings, user)
    )

    assert response.status_code == 422
```

Append to `backend/tests/unit/test_i18n.py`:

```python
from app.core.i18n import MESSAGES, SUPPORTED_LOCALES


def test_every_locale_defines_the_same_keys() -> None:
    assert set(MESSAGES) == set(SUPPORTED_LOCALES)
    assert {frozenset(catalog) for catalog in MESSAGES.values()} == {frozenset(MESSAGES["en"])}
```

(Merge the import with the file's existing `from app.core.i18n import t`.)

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/api/identity/test_magic_link.py tests/api/identity/test_me.py tests/unit/test_i18n.py -v`
Expected: FAIL — `ImportError: cannot import name 'HandlerDeps' from 'app.wiring'` (conftest import).

- [ ] **Step 5: Implement**

Add to `backend/app/modules/identity/schemas.py` (the file already imports `Literal`, `ClassVar`, `DomainEvent`; add `from app.core.i18n import Locale`):

```python
SignInPurpose = Literal["sign_in"]


class MeUpdate(BaseModel):
    locale: Locale


class AccountContact(BaseModel):
    email: str
    locale: str


class MagicLinkRequested(DomainEvent):
    event_type: ClassVar[str] = "identity.magic_link_requested"
    purpose: SignInPurpose = "sign_in"
```

and add `locale: str` as the last field of `MeResponse`.

`backend/app/modules/identity/accounts.py`:

```python
"""Account operations other modules need (via identity.service)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.outbox.writer import emit_event
from app.modules.identity.repository import UserRepository
from app.modules.identity.schemas import AccountContact, MagicLinkRequested, SignInPurpose


async def account_contact(session: AsyncSession, user_id: UUID) -> AccountContact:
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise NotFound("Account not found", code="account_not_found")
    return AccountContact(email=user.email, locale=user.locale)


async def request_sign_in_link(
    session: AsyncSession, user_id: UUID, *, purpose: SignInPurpose
) -> None:
    """Queues a sign-in link. The worker process issues the token and sends
    the mail, so no request's response time depends on the mail server."""
    await emit_event(session, MagicLinkRequested(aggregate_id=user_id, purpose=purpose))
```

Replace `backend/app/modules/identity/magic_link.py` with:

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
from app.modules.identity.accounts import request_sign_in_link
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import UserRepository, normalize_email
from app.modules.identity.tokens import hash_token, new_opaque_token

TOKEN_PREFIX = "magiclink:"
# i18n key prefix per purpose; Task 8 adds "invitation".
_TEMPLATES = {"sign_in": "magic_link"}
log = structlog.get_logger(__name__)


def _eligible(user: UserAccount | None) -> bool:
    return (
        user is not None
        and user.role is UserRole.WORKER
        and user.status is AccountStatus.ACTIVE
    )


class MagicLinkService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.users = UserRepository(session)

    async def request(self, email: str, client_ip: str) -> None:
        """Behaves the same whether or not the email exists, so the endpoint
        cannot be used to discover who works with Bonarda. The link itself is
        issued and mailed by the worker (send_magic_link)."""
        email = normalize_email(email)
        s = self.settings
        await self._limit(f"ml:rate:email:{hash_token(email)}", s.magic_link_per_email_per_hour)
        await self._limit(f"ml:rate:ip:{client_ip}", s.magic_link_per_ip_per_hour)
        user = await self.users.get_by_email(email)
        if user is None or not _eligible(user):
            log.info("auth.magic_link_not_sent")
            return
        await request_sign_in_link(self.session, user.id, purpose="sign_in")

    async def _limit(self, key: str, limit: int) -> None:
        # SET NX (only if absent) then INCR in one MULTI/EXEC: the key always
        # carries a TTL from the moment it is created.
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(key, 0, ex=3600, nx=True)
            pipe.incr(key)
            _, count = await pipe.execute()
        if count > limit:
            raise TooManyRequests(
                "Too many sign-in link requests; try again later", code="magic_link_rate_limited"
            )

    async def verify(self, token: str) -> UserAccount:
        invalid = Unauthorized(
            "This sign-in link is invalid or has expired", code="magic_link_invalid"
        )
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


async def send_magic_link(
    session: AsyncSession,
    *,
    redis: Redis,
    settings: Settings,
    mailer: Mailer,
    user_id: UUID,
    purpose: str,
) -> bool:
    """Runs in the worker (outbox handler). Re-checks eligibility, because the
    account may have changed since the request was queued."""
    user = await UserRepository(session).get(user_id)
    if user is None or not _eligible(user):
        log.info("auth.magic_link_skipped", user_id=str(user_id))
        return False
    token = new_opaque_token()
    await redis.set(
        TOKEN_PREFIX + hash_token(token), str(user.id), ex=settings.magic_link_ttl_seconds
    )
    # The token travels in the URL fragment so it never reaches server logs.
    link = f"{settings.public_app_url}/auth/verify#token={token}"
    prefix = _TEMPLATES[purpose]
    params = {
        "minutes": settings.magic_link_ttl_seconds // 60,
        "link": link,
        "sign_in_url": f"{settings.public_app_url}/sign-in",
    }
    await mailer.send(
        to=user.email,
        subject=t(f"{prefix}.subject", user.locale),
        body=t(f"{prefix}.body", user.locale, **params),
    )
    return True
```

`backend/app/modules/identity/handlers.py`:

```python
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.identity.magic_link import send_magic_link
from app.modules.identity.schemas import MagicLinkRequested


def register(
    registry: HandlerRegistry, *, redis: Redis, settings: Settings, mailer: Mailer
) -> None:
    async def send_link(session: AsyncSession, payload: dict[str, Any]) -> None:
        await send_magic_link(
            session,
            redis=redis,
            settings=settings,
            mailer=mailer,
            user_id=UUID(payload["aggregate_id"]),
            purpose=payload.get("purpose", "sign_in"),
        )

    registry.register(MagicLinkRequested, "identity.send_magic_link", send_link)
```

In `backend/app/modules/identity/router.py`:
- Remove the `MailerDep` import and the `mailer: MailerDep` parameter from both magic-link routes; construct `MagicLinkService(session, redis, settings)`.
- Add `MeUpdate` to the schemas import and replace the `me` route with:

```python
def _me_response(user: UserAccount) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        worker_id=user.worker_id,
        can_view_governance=user.can_view_governance,
        locale=user.locale,
    )


async def _current_account(actor: Actor, session: AsyncSession) -> UserAccount:
    user = await UserRepository(session).get(actor.user_id)
    if user is None:
        raise Unauthorized("Account no longer exists", code="account_inactive")
    return user


@router.get("/me")
async def me(actor: CurrentActor, session: SessionDep) -> MeResponse:
    return _me_response(await _current_account(actor, session))


@router.patch("/me")
async def update_me(body: MeUpdate, actor: CurrentActor, session: SessionDep) -> MeResponse:
    user = await _current_account(actor, session)
    user.locale = body.locale
    return _me_response(user)
```

(Add imports `from sqlalchemy.ext.asyncio import AsyncSession` and `from app.modules.identity.models import UserAccount`.)

Replace `backend/app/modules/identity/service.py` with:

```python
"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.accounts import account_contact, request_sign_in_link
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
    "account_contact",
    "request_sign_in_link",
    "require_permission",
    "require_visibility",
]
```

Replace `backend/app/wiring.py` with:

```python
"""Composition root: the only place that knows every module's handlers and
visibility sources, and what each handler needs to run."""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.identity import handlers as identity_handlers
from app.modules.identity.service import VisibilitySource


@dataclass(frozen=True, slots=True)
class HandlerDeps:
    settings: Settings
    redis: Redis
    mailer: Mailer


def build_registry(deps: HandlerDeps) -> HandlerRegistry:
    registry = HandlerRegistry()
    identity_handlers.register(
        registry, redis=deps.redis, settings=deps.settings, mailer=deps.mailer
    )
    return registry


def visibility_sources() -> list[VisibilitySource]:
    return []
```

In `backend/app/worker/settings.py`:
- Add imports `from redis.asyncio import Redis`, `from app.modules.integrations.service import build_mailer`, and change `from app.wiring import build_registry` to `from app.wiring import HandlerDeps, build_registry`.
- In `startup`, replace `ctx["registry"] = build_registry()` with:

```python
    # A separate client with decoded responses, matching the API's client:
    # ctx["redis"] is Arq's own byte-oriented pool.
    handler_redis = Redis.from_url(
        settings.redis_url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0
    )
    ctx["handler_redis"] = handler_redis
    ctx["registry"] = build_registry(
        HandlerDeps(settings=settings, redis=handler_redis, mailer=build_mailer(settings))
    )
```

- In `shutdown`, after `await ctx["relay_task"]`, add `await ctx["handler_redis"].aclose()`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/api/identity/test_magic_link.py tests/api/identity/test_me.py tests/unit/test_i18n.py -v`
Expected: 16 passed.

- [ ] **Step 7: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(identity): per-account locale; sign-in links mailed by the worker"
```

---

### Task 3: Identity carry-forward fixes

**Files:**
- Modify: `backend/app/modules/identity/magic_link.py`, `backend/app/modules/identity/scim.py`, `backend/app/modules/identity/oidc_login.py`
- Test: `backend/tests/api/identity/test_magic_link.py`, `backend/tests/api/identity/test_scim.py`, `backend/tests/api/identity/test_oidc_login.py`

**Interfaces:**
- Consumes: `RefreshSessionRepository.revoke_all_for_user(user_id, at, *, reason)`, `mark_revoked(redis, settings, user_id, at)`.
- Produces: error code `scim_unsupported_operation`; SCIM rejects the `worker` role with `scim_invalid_value`; a login that changes a staff member's role revokes their other sessions.

Role authority (records the roadmap carry-forward decision): the identity provider is the only source of staff roles, through two channels — SCIM pushes changes immediately, and OIDC login reconciles from `groups`. Both apply the IdP's current answer, and both now revoke existing sessions when the role changes, so no device keeps a stale role.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/identity/test_magic_link.py`:

```python
async def test_verify_rejects_link_if_account_is_no_longer_a_worker(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer, drain: Drain
) -> None:
    worker = await make_user(session, role=UserRole.WORKER, email="kofi@example.com")
    await client.post("/api/v1/auth/magic-link", json={"email": "kofi@example.com"})
    await drain()
    worker.role = UserRole.PM
    await session.commit()

    response = await client.post("/api/v1/auth/magic-link/verify", json={"token": mailer.token()})

    assert response.status_code == 401
    assert response.json()["code"] == "magic_link_invalid"
```

Append to `backend/tests/api/identity/test_scim.py`:

```python
@pytest.mark.parametrize("path", ["active", "roles"])
async def test_removing_a_managed_attribute_is_rejected(
    client: AsyncClient, session: AsyncSession, path: str
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama", json=_patch({"op": "remove", "path": path}), headers=SCIM
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_unsupported_operation"


async def test_removing_an_unmanaged_attribute_is_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "remove", "path": "name.givenName"}),
        headers=SCIM,
    )

    assert response.status_code == 200
    await session.refresh(user)
    assert user.status is AccountStatus.ACTIVE


async def test_unknown_operation_is_rejected(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "copy", "path": "active", "value": False}),
        headers=SCIM,
    )

    assert response.json()["code"] == "scim_unsupported_operation"


async def test_staff_account_cannot_be_given_the_worker_role(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": "roles", "value": [{"value": "worker"}]}),
        headers=SCIM,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_invalid_value"
```

Append to `backend/tests/api/identity/test_oidc_login.py` (add imports `from datetime import timedelta`, `from app.core.config import Settings`, `from app.core.time import utcnow`, `from app.modules.identity.models import RefreshSession`, `from app.modules.identity.sessions import SessionService`, and `bearer` from `tests.support`):

```python
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
        subject="kc-ama", email="ama@bonarda.works", amr=["otp"], acr=None,
        groups=["bonarda-finance"],
    )
    state = await _login(client)

    response = await client.get(
        "/api/v1/auth/oidc/callback", params={"code": "c", "state": state}
    )

    assert response.status_code == 302
    sessions = (
        await session.scalars(select(RefreshSession).where(RefreshSession.user_id == user.id))
    ).all()
    revoked = [s for s in sessions if s.revoked_at is not None]
    assert [s.revoked_reason for s in revoked] == ["admin"]
    assert len(sessions) == 2  # the old one (revoked) and the one this login issued
    stale = await client.get("/api/v1/me", headers=old_token)
    assert stale.json()["code"] == "session_revoked"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/identity/test_magic_link.py tests/api/identity/test_scim.py tests/api/identity/test_oidc_login.py -v`
Expected: the 7 new tests FAIL (verify returns 200; SCIM ops return 200; old sessions stay live); existing tests pass.

- [ ] **Step 3: Implement**

In `backend/app/modules/identity/magic_link.py`, change the eligibility check in `verify` from `if user is None or user.status is not AccountStatus.ACTIVE:` to:

```python
        if user is None or not _eligible(user):
```

In `backend/app/modules/identity/scim.py`, replace `_parse_role` and `_interpret` with:

```python
_SUPPORTED_OPS = ("add", "replace", "remove")
_MANAGED_PATHS = ("active", "roles")


def _unsupported(detail: str) -> BadRequest:
    return BadRequest(detail, code="scim_unsupported_operation")


def _parse_role(value: Any) -> UserRole:
    try:
        role = UserRole(value[0]["value"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise _invalid('\'roles\' must be a list like [{"value": "pm"}]') from exc
    if role is UserRole.WORKER:
        raise _invalid("Staff accounts cannot be given the worker role")
    return role


def _interpret(patch: ScimPatch) -> _Changes:
    """Applies `active` and `roles`. Other attributes (names, emails, manager)
    are accepted and ignored: this system does not store them."""
    changes = _Changes()
    for operation in patch.operations:
        op = operation.op.lower()
        if op not in _SUPPORTED_OPS:
            raise _unsupported(f"Unsupported SCIM operation '{operation.op}'")
        if op == "remove":
            if operation.path in _MANAGED_PATHS:
                raise _unsupported(f"'{operation.path}' cannot be removed; replace it instead")
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
```

In `backend/app/modules/identity/oidc_login.py`:
- Add imports: `from datetime import timedelta`, `from uuid import UUID`, `import structlog`, `from redis.exceptions import RedisError`, `from app.core.time import utcnow`, `from app.modules.identity.repository import RefreshSessionRepository` (merge with the existing repository import), `from app.modules.identity.revocation import mark_revoked`, and `log = structlog.get_logger(__name__)` below the constants.
- In `_upsert`, at the end of the `if user.role is not role:` branch (after its `write_audit`), add:

```python
            await RefreshSessionRepository(self.session).revoke_all_for_user(
                user.id, utcnow(), reason="admin"
            )
            await self._mark_revoked_quietly(user.id)
```

- Add this method to `OidcLoginService`:

```python
    async def _mark_revoked_quietly(self, user_id: UUID) -> None:
        # One second in the past: tokens from before this login stop working,
        # while the session this login is about to issue stays valid.
        try:
            await mark_revoked(
                self.redis, self.settings, user_id, utcnow() - timedelta(seconds=1)
            )
        except (RedisError, OSError):
            log.error("auth.revocation_marker_unavailable", user_id=str(user_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/identity -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "fix(identity): SCIM op validation, worker-role guard, revoke on login role change"
```

---

### Task 4: Passport schema, foreign keys and test support

**Files:**
- Create: `backend/app/modules/passport/__init__.py`, `backend/app/modules/passport/enums.py`, `backend/app/modules/passport/models.py`, `backend/alembic/versions/0005_passport.py`
- Modify: `backend/app/modules/identity/models.py`, `backend/app/modules/identity/grants.py`, `backend/app/models_registry.py`, `backend/app/main.py`, `backend/app/worker/settings.py`
- Modify tests: `backend/tests/support.py`, `backend/tests/integration/test_visibility_policy.py`, `backend/tests/api/identity/test_access_grants.py`, `backend/tests/api/identity/test_scim.py`
- Test: `backend/tests/integration/test_passport_schema.py`

**Interfaces:**
- Produces:
  - Enums (`app.modules.passport.enums`, all `StrEnum`): `WorkerType{FREELANCER="freelancer", CONTRACTOR="contractor"}`, `WorkerStatus{ACTIVE, DORMANT, OFFBOARDED, ANONYMIZED}`, `OnboardingState{INVITED="invited", PROFILE_COMPLETE="profile_complete"}`, `StandingTier{UNRATED, TIER_1="tier_1", TIER_2="tier_2"}`, `AvailabilityStatus{AVAILABLE, AVAILABLE_FROM="available_from", UNAVAILABLE}`, `VerificationStatus{UNVERIFIED, SELF_REPORTED="self_reported", BONARDA_VERIFIED="bonarda_verified"}`, `ClaimSource{SELF="self", EXTERNAL="external", REVIEW="review"}`, `ConsentPurpose{CROSS_REGION_MATCHING="cross_region_matching", EXTERNAL_PREFILL="external_prefill"}`.
  - Models `Worker`, `Skill`, `SkillClaim`, `Consent` (tables `workers`, `skills`, `skill_claims`, `consents`).
  - FKs `fk_user_accounts_worker_id` (RESTRICT) and `fk_access_grants_scoped_worker_id` (CASCADE).
  - `GrantService.create` rejects an unknown `scoped_worker_id` with `400 grant_worker_not_found`.
  - Test helper `make_worker(session, *, email=None, full_name="Kofi Mensah", data_region="GH", status=WorkerStatus.DORMANT, onboarding_state=OnboardingState.PROFILE_COMPLETE, locale="en") -> tuple[Worker, UserAccount]`. `make_user(role=WORKER)` now creates a real `workers` row.

Data model notes (deviations from `bonarda-data-models.md`, recorded in the roadmap in Task 9): `workers` has no `email` or `locale` column — contact email and locale live on the worker's `user_accounts` row, so there is one source of truth for each.

- [ ] **Step 1: Enums and models**

`backend/app/modules/passport/__init__.py`: empty file.

`backend/app/modules/passport/enums.py`:

```python
import enum


class WorkerType(enum.StrEnum):
    FREELANCER = "freelancer"
    CONTRACTOR = "contractor"  # employees later, without a breaking change (NFR-6.2)


class WorkerStatus(enum.StrEnum):
    ACTIVE = "active"  # has an active engagement
    DORMANT = "dormant"  # no active engagement; still searchable (FR-9.7)
    OFFBOARDED = "offboarded"
    ANONYMIZED = "anonymized"  # erasure / retention expiry


class OnboardingState(enum.StrEnum):
    INVITED = "invited"
    PROFILE_COMPLETE = "profile_complete"


class StandingTier(enum.StrEnum):
    UNRATED = "unrated"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"  # "Trusted"


class AvailabilityStatus(enum.StrEnum):
    AVAILABLE = "available"
    AVAILABLE_FROM = "available_from"
    UNAVAILABLE = "unavailable"


class VerificationStatus(enum.StrEnum):
    UNVERIFIED = "unverified"
    SELF_REPORTED = "self_reported"
    BONARDA_VERIFIED = "bonarda_verified"  # distinct reviewers ≥ policy threshold (FR-2.2)


class ClaimSource(enum.StrEnum):
    SELF = "self"
    EXTERNAL = "external"
    REVIEW = "review"


class ConsentPurpose(enum.StrEnum):
    CROSS_REGION_MATCHING = "cross_region_matching"  # NFR-4.3
    EXTERNAL_PREFILL = "external_prefill"
```

`backend/app/modules/passport/models.py`:

```python
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.passport.enums import (
    AvailabilityStatus,
    ClaimSource,
    ConsentPurpose,
    OnboardingState,
    StandingTier,
    VerificationStatus,
    WorkerStatus,
    WorkerType,
)


class Worker(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The persistent passport (FR-1.1). Never hard-deleted: erasure is
    anonymization (spec §6.3). Contact email and locale live on the worker's
    user_accounts row."""

    __tablename__ = "workers"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    worker_type: Mapped[WorkerType] = mapped_column(pg_enum(WorkerType), nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        pg_enum(WorkerStatus),
        default=WorkerStatus.DORMANT,
        server_default=WorkerStatus.DORMANT.value,
        nullable=False,
    )
    onboarding_state: Mapped[OnboardingState] = mapped_column(
        pg_enum(OnboardingState),
        default=OnboardingState.INVITED,
        server_default=OnboardingState.INVITED.value,
        nullable=False,
    )
    standing_tier: Mapped[StandingTier] = mapped_column(
        pg_enum(StandingTier),
        default=StandingTier.UNRATED,
        server_default=StandingTier.UNRATED.value,
        nullable=False,
    )
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    base_location: Mapped[str | None] = mapped_column(String(120))
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(10)), default=list, server_default=text("'{}'"), nullable=False
    )
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        pg_enum(AvailabilityStatus),
        default=AvailabilityStatus.AVAILABLE,
        server_default=AvailabilityStatus.AVAILABLE.value,
        nullable=False,
    )
    available_from: Mapped[date | None] = mapped_column(Date)
    dormant_since: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (Index("ix_workers_status_region", "status", "data_region"),)


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled taxonomy: free-text skill names cannot be searched reliably."""

    __tablename__ = "skills"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)


class SkillClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_claims"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        pg_enum(VerificationStatus),
        default=VerificationStatus.SELF_REPORTED,
        server_default=VerificationStatus.SELF_REPORTED.value,
        nullable=False,
    )
    source: Mapped[ClaimSource] = mapped_column(
        pg_enum(ClaimSource),
        default=ClaimSource.SELF,
        server_default=ClaimSource.SELF.value,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("worker_id", "skill_id", name="uq_skill_claims_worker_skill"),
        Index("ix_skill_claims_skill_id", "skill_id"),
    )


class Consent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current consent per purpose; every change is also in audit_log."""

    __tablename__ = "consents"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[ConsentPurpose] = mapped_column(pg_enum(ConsentPurpose), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(80), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("worker_id", "purpose", name="uq_consents_worker_purpose"),
    )
```

In `backend/app/modules/identity/models.py`:
- `UserAccount.worker_id` becomes `mapped_column(PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), unique=True)`; delete the "added by Plan 2's migration" comment.
- `AccessGrant.scoped_worker_id` becomes `mapped_column(PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)`; delete its comment.

Replace `backend/app/models_registry.py` with:

```python
"""Imports every ORM model so Base.metadata is complete for Alembic, tests,
and the API/worker processes (cross-module FKs resolve by table name)."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models
from app.modules.identity import models as identity_models
from app.modules.passport import models as passport_models

__all__ = ["audit_models", "identity_models", "outbox_models", "passport_models"]
```

Add `from app import models_registry as _models_registry  # noqa: F401  (map every table before first flush)` near the top of both `backend/app/main.py` and `backend/app/worker/settings.py`. (Don't write `import app.models_registry`: it binds the name `app`, which `main.py` also uses for the FastAPI instance.)

- [ ] **Step 2: Migration**

`backend/alembic/versions/0005_passport.py`:

```python
"""passport: workers, skills, skill claims, consents; FKs from identity to workers

Revision ID: 0005_passport
Revises: 0004_user_locale

Adding the FKs fails if user_accounts.worker_id or access_grants.scoped_worker_id
hold ids with no workers row (possible only in a dev database built before this
plan). That failure is deliberate: fix or delete such rows by hand rather than
have a migration silently delete data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_passport"
down_revision: str | None = "0004_user_locale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column(
        "id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(),
        nullable=False,
    )


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
        "workers",
        _id(),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column(
            "worker_type", sa.Enum("freelancer", "contractor", name="workertype"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("active", "dormant", "offboarded", "anonymized", name="workerstatus"),
            server_default="dormant",
            nullable=False,
        ),
        sa.Column(
            "onboarding_state",
            sa.Enum("invited", "profile_complete", name="onboardingstate"),
            server_default="invited",
            nullable=False,
        ),
        sa.Column(
            "standing_tier",
            sa.Enum("unrated", "tier_1", "tier_2", name="standingtier"),
            server_default="unrated",
            nullable=False,
        ),
        sa.Column("data_region", sa.String(8), nullable=False),
        sa.Column("base_location", sa.String(120), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(10)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "availability_status",
            sa.Enum("available", "available_from", "unavailable", name="availabilitystatus"),
            server_default="available",
            nullable=False,
        ),
        sa.Column("available_from", sa.Date(), nullable=True),
        sa.Column("dormant_since", sa.Date(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_workers"),
    )
    op.create_index("ix_workers_status_region", "workers", ["status", "data_region"])

    op.create_table(
        "skills",
        _id(),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name_i18n", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_skills"),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
    )

    op.create_table(
        "skill_claims",
        _id(),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "verification_status",
            sa.Enum("unverified", "self_reported", "bonarda_verified", name="verificationstatus"),
            server_default="self_reported",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum("self", "external", "review", name="claimsource"),
            server_default="self",
            nullable=False,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_skill_claims"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_skill_claims_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_skill_claims_skill_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("worker_id", "skill_id", name="uq_skill_claims_worker_skill"),
    )
    op.create_index("ix_skill_claims_skill_id", "skill_claims", ["skill_id"])

    op.create_table(
        "consents",
        _id(),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("cross_region_matching", "external_prefill", name="consentpurpose"),
            nullable=False,
        ),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("legal_basis", sa.String(80), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_consents_worker_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("worker_id", "purpose", name="uq_consents_worker_purpose"),
    )

    op.create_foreign_key(
        "fk_user_accounts_worker_id", "user_accounts", "workers", ["worker_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_access_grants_scoped_worker_id", "access_grants", "workers",
        ["scoped_worker_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_access_grants_scoped_worker_id", "access_grants", type_="foreignkey")
    op.drop_constraint("fk_user_accounts_worker_id", "user_accounts", type_="foreignkey")
    op.drop_table("consents")
    op.drop_index("ix_skill_claims_skill_id", table_name="skill_claims")
    op.drop_table("skill_claims")
    op.drop_table("skills")
    op.drop_index("ix_workers_status_region", table_name="workers")
    op.drop_table("workers")
    for enum_name in (
        "consentpurpose", "claimsource", "verificationstatus", "availabilitystatus",
        "standingtier", "onboardingstate", "workerstatus", "workertype",
    ):
        op.execute(f"DROP TYPE {enum_name}")
```

- [ ] **Step 3: Test support and existing tests**

In `backend/tests/support.py`, add imports `from app.modules.passport.enums import OnboardingState, WorkerStatus, WorkerType` and `from app.modules.passport.models import Worker`, then replace `make_user` and add `make_worker`:

```python
async def make_user(
    session: AsyncSession,
    *,
    role: UserRole = UserRole.PM,
    email: str | None = None,
    status: AccountStatus = AccountStatus.ACTIVE,
    oidc_subject: str | None = None,
    worker_id: UUID | None = None,
    locale: str = "en",
) -> UserAccount:
    is_worker = role is UserRole.WORKER
    if is_worker and worker_id is None:
        worker = Worker(
            full_name="Test Worker", worker_type=WorkerType.FREELANCER, data_region="GH"
        )
        session.add(worker)
        await session.flush()
        worker_id = worker.id
    user = UserAccount(
        email=(email or f"{uuid4().hex[:10]}@example.com").strip().lower(),
        role=role,
        auth_provider=AuthProvider.MAGIC_LINK if is_worker else AuthProvider.CORPORATE_SSO,
        status=status,
        oidc_subject=oidc_subject if not is_worker else None,
        worker_id=worker_id if is_worker else None,
        locale=locale,
    )
    session.add(user)
    await session.commit()
    return user


async def make_worker(
    session: AsyncSession,
    *,
    email: str | None = None,
    full_name: str = "Kofi Mensah",
    data_region: str = "GH",
    status: WorkerStatus = WorkerStatus.DORMANT,
    onboarding_state: OnboardingState = OnboardingState.PROFILE_COMPLETE,
    locale: str = "en",
) -> tuple[Worker, UserAccount]:
    worker = Worker(
        full_name=full_name,
        worker_type=WorkerType.FREELANCER,
        data_region=data_region,
        status=status,
        onboarding_state=onboarding_state,
    )
    session.add(worker)
    await session.flush()
    user = await make_user(
        session, role=UserRole.WORKER, email=email, worker_id=worker.id, locale=locale
    )
    return worker, user
```

In `backend/tests/integration/test_visibility_policy.py`, import `make_worker` from `tests.support`, and in `test_active_grant_gives_pm_detail` and `test_expired_or_revoked_grant_gives_nothing` replace `worker_id = uuid4()` with:

```python
    worker, _ = await make_worker(session)
    worker_id = worker.id
```

In `backend/tests/api/identity/test_access_grants.py`:
- Import `make_worker` from `tests.support` and `UUID` from `uuid`.
- Change `_body` to take the scoped worker explicitly, defaulting to a random id for tests that fail validation before the worker matters:

```python
def _body(
    granted_to: object, *, scoped_worker_id: UUID | None = None, **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "granted_to_id": str(granted_to),
        "scoped_worker_id": str(scoped_worker_id or uuid4()),
        "reason": "Cross-team staffing for Project Volta",
        "expires_at": (utcnow() + timedelta(days=7)).isoformat(),
    }
    body.update(overrides)
    return body
```

- In `test_people_ops_grants_pm_temporary_access` and `test_list_and_revoke`, create a worker first (`worker, _ = await make_worker(session)`) and pass `scoped_worker_id=worker.id` to every `_body(...)` call in those tests.
- In `test_sweep_records_lapsed_grants_once`, create `worker, _ = await make_worker(session)` and use `scoped_worker_id=worker.id` for both `AccessGrant` rows.
- Add:

```python
async def test_grant_for_unknown_worker_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/access-grants", json=_body(pm.id), headers=bearer(settings, ops)
    )

    assert response.status_code == 400
    assert response.json()["code"] == "grant_worker_not_found"
    assert (await session.scalars(select(AccessGrant))).all() == []
```

In `backend/tests/api/identity/test_scim.py`, in `test_deactivation_closes_open_access_grants`, create `worker, _ = await make_worker(session)` before building the grant and use `scoped_worker_id=worker.id` (import `make_worker`; drop `uuid4` if now unused).

`backend/tests/integration/test_passport_schema.py`:

```python
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import ConsentPurpose
from app.modules.passport.models import Consent, Skill, SkillClaim
from tests.support import make_worker


async def test_a_worker_account_must_point_at_a_real_worker(session: AsyncSession) -> None:
    session.add(
        UserAccount(
            email="ghost@example.com",
            role=UserRole.WORKER,
            auth_provider=AuthProvider.MAGIC_LINK,
            worker_id=uuid4(),
        )
    )

    with pytest.raises(IntegrityError, match="fk_user_accounts_worker_id"):
        await session.commit()


async def test_a_worker_claims_each_skill_once(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.flush()
    session.add_all(
        [SkillClaim(worker_id=worker.id, skill_id=skill.id) for _ in range(2)]
    )

    with pytest.raises(IntegrityError, match="uq_skill_claims_worker_skill"):
        await session.commit()


async def test_one_consent_row_per_purpose(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    session.add_all(
        [
            Consent(
                worker_id=worker.id,
                purpose=ConsentPurpose.CROSS_REGION_MATCHING,
                granted=True,
                legal_basis="consent",
            )
            for _ in range(2)
        ]
    )

    with pytest.raises(IntegrityError, match="uq_consents_worker_purpose"):
        await session.commit()
```

- [ ] **Step 4: Run tests to verify the new ones fail**

Run: `pytest tests/integration/test_passport_schema.py tests/api/identity/test_access_grants.py -v`
Expected: `test_grant_for_unknown_worker_is_rejected` FAILS (500 from an unhandled `IntegrityError`, or 201 if the FK is somehow missing); the schema tests pass.

- [ ] **Step 5: Validate the scoped worker in `GrantService.create`**

In `backend/app/modules/identity/grants.py`, add `from sqlalchemy.exc import IntegrityError` and replace the block from `grant = self.grants.add(` through `await self.session.flush()` with:

```python
        # identity does not import passport: the FK to workers is the check.
        # A savepoint keeps the outer transaction usable if it fails.
        try:
            async with self.session.begin_nested():
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
        except IntegrityError as exc:
            raise BadRequest("No worker with this id", code="grant_worker_not_found") from exc
```

- [ ] **Step 6: Run the whole suite**

Run: `pytest -v`
Expected: all pass, including the migration tests (models, check-constraint names, round trip) and every existing identity test (worker accounts now have real `workers` rows).

- [ ] **Step 7: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(passport): worker, skill, claim and consent tables with identity FKs"
```

---

### Task 5: Skills taxonomy and worker skill claims

**Files:**
- Create: `backend/app/modules/passport/repository.py`, `backend/app/modules/passport/schemas.py`, `backend/app/modules/passport/dependencies.py`, `backend/app/modules/passport/skills.py`, `backend/app/modules/passport/router.py`, `backend/app/modules/passport/service.py`
- Modify: `backend/app/modules/identity/permissions.py`, `docs/permissions.md` (regenerated), `backend/app/main.py`
- Test: `backend/tests/api/passport/__init__.py`, `backend/tests/api/passport/test_skills.py`

**Interfaces:**
- Consumes: `CurrentActor`, `require_permission`, `Permission` (identity.service); `write_audit`, `emit_event`.
- Produces:
  - `Permission.SKILL_MANAGE = "skill:manage"` granted to `people_ops`.
  - Repositories: `WorkerRepository(session)` with `get(worker_id) -> Worker | None`, `add(worker) -> Worker`; `SkillRepository` with `get`, `get_by_slug`, `search(q, limit) -> list[Skill]`, `add`; `SkillClaimRepository` with `list_for_worker(worker_id) -> list[tuple[SkillClaim, Skill]]`, `get(worker_id, skill_id)`, `add`, `delete(claim)`. (Task 7 adds `ConsentRepository`.)
  - Schemas: `SkillCreate(slug, name_i18n)`, `SkillRead(id, slug, name_i18n)`, `SkillClaimCreate(skill_id)`, `WorkerSkill(skill_id, slug, verification_status)`, event `WorkerUpdated(aggregate_id, fields: list[str])` with `event_type = "passport.worker_updated"`.
  - `WorkerActor(actor: Actor, worker_id: UUID)`; dependencies `WorkerReader`, `WorkerEditor`.
  - `SkillService(session)`: `create(actor, data) -> Skill`, `search(q, limit) -> list[Skill]`. `ClaimService(session)`: `claim(who, skill_id) -> WorkerSkill`, `remove(who, skill_id) -> None`.
  - Error codes: `skill_slug_taken` (409), `skill_not_found` (404), `skill_already_claimed` (409), `claim_not_found` (404), `skill_verified_locked` (409), `not_a_worker` (403).
  - Routes: `GET /api/v1/skills?q=&limit=`, `POST /api/v1/skills` (201), `POST /api/v1/workers/me/skills` (201), `DELETE /api/v1/workers/me/skills/{skill_id}` (204).

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/passport/__init__.py`: empty file.

`backend/tests/api/passport/test_skills.py`:

```python
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from tests.support import bearer, make_user, make_worker


async def _skill(session: AsyncSession, slug: str, en: str, fr: str | None = None) -> Skill:
    names = {"en": en} | ({"fr": fr} if fr else {})
    skill = Skill(slug=slug, name_i18n=names)
    session.add(skill)
    await session.commit()
    return skill


async def test_people_ops_adds_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "data-analysis", "name_i18n": {"en": "Data analysis", "fr": "Analyse"}},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "data-analysis"
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id) == ("skill.created", ops.id)


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "Data Analysis", "name_i18n": {"en": "Data analysis"}},
        {"slug": "data-analysis", "name_i18n": {"fr": "Analyse"}},
        {"slug": "data-analysis", "name_i18n": {"en": ""}},
    ],
)
async def test_invalid_skill_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, body: dict[str, object]
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post("/api/v1/skills", json=body, headers=bearer(settings, ops))

    assert response.status_code == 422


async def test_duplicate_slug_is_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _skill(session, "data-analysis", "Data analysis")

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "data-analysis", "name_i18n": {"en": "Data analysis"}},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "skill_slug_taken"


async def test_pm_cannot_add_skills(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "x", "name_i18n": {"en": "X"}},
        headers=bearer(settings, pm),
    )

    assert response.status_code == 403


async def test_search_matches_slug_and_localized_names(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)
    await _skill(session, "data-analysis", "Data analysis", "Analyse de données")
    await _skill(session, "project-management", "Project management", "Gestion de projet")
    headers = bearer(settings, user)

    by_slug = await client.get("/api/v1/skills", params={"q": "data"}, headers=headers)
    by_french = await client.get("/api/v1/skills", params={"q": "gestion"}, headers=headers)
    everything = await client.get("/api/v1/skills", params={"limit": 1}, headers=headers)

    assert [s["slug"] for s in by_slug.json()] == ["data-analysis"]
    assert [s["slug"] for s in by_french.json()] == ["project-management"]
    assert len(everything.json()) == 1


@pytest.mark.parametrize("term", ["%", "_", "data%"])
async def test_search_treats_wildcards_literally(
    client: AsyncClient, session: AsyncSession, settings: Settings, term: str
) -> None:
    user = await make_user(session, role=UserRole.PM)
    await _skill(session, "data-analysis", "Data analysis")

    response = await client.get(
        "/api/v1/skills", params={"q": term}, headers=bearer(settings, user)
    )

    assert response.json() == []


async def test_worker_claims_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")

    response = await client.post(
        "/api/v1/workers/me/skills",
        json={"skill_id": str(skill.id)},
        headers=bearer(settings, account),
    )

    assert response.status_code == 201
    assert response.json() == {
        "skill_id": str(skill.id),
        "slug": "data-analysis",
        "verification_status": "self_reported",
    }
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "passport.worker_updated"
    assert event.payload == {"aggregate_id": str(worker.id), "fields": ["skills"]}


async def test_claiming_twice_or_an_unknown_skill_fails(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    headers = bearer(settings, account)
    await client.post("/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=headers)

    again = await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=headers
    )
    unknown = await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(uuid4())}, headers=headers
    )

    assert again.json()["code"] == "skill_already_claimed"
    assert unknown.json()["code"] == "skill_not_found"


async def test_staff_cannot_claim_skills(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    skill = await _skill(session, "data-analysis", "Data analysis")

    response = await client.post(
        "/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=bearer(settings, pm)
    )

    assert response.status_code == 403


async def test_worker_removes_a_self_reported_claim(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    session.add(SkillClaim(worker_id=worker.id, skill_id=skill.id))
    await session.commit()

    response = await client.delete(
        f"/api/v1/workers/me/skills/{skill.id}", headers=bearer(settings, account)
    )

    assert response.status_code == 204
    assert (await session.scalars(select(SkillClaim))).all() == []


async def test_verified_claims_cannot_be_removed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    session.add(
        SkillClaim(
            worker_id=worker.id,
            skill_id=skill.id,
            verification_status=VerificationStatus.BONARDA_VERIFIED,
        )
    )
    await session.commit()
    headers = bearer(settings, account)

    locked = await client.delete(f"/api/v1/workers/me/skills/{skill.id}", headers=headers)
    missing = await client.delete(f"/api/v1/workers/me/skills/{uuid4()}", headers=headers)

    assert locked.json()["code"] == "skill_verified_locked"
    assert missing.json()["code"] == "claim_not_found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/passport/test_skills.py -v`
Expected: FAIL — 404 responses for `/api/v1/skills` (routes don't exist).

- [ ] **Step 3: Implement**

In `backend/app/modules/identity/permissions.py`, add `SKILL_MANAGE = "skill:manage"` to `Permission` (after `AUDIT_READ`) and add `P.SKILL_MANAGE` to the `PEOPLE_OPS` set. Then regenerate the docs:

```bash
python -m app.modules.identity.permissions ../docs/permissions.md
```

`backend/app/modules/passport/repository.py`:

```python
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.passport.models import Skill, SkillClaim, Worker


class WorkerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, worker_id: UUID) -> Worker | None:
        return await self.session.get(Worker, worker_id)

    def add(self, worker: Worker) -> Worker:
        self.session.add(worker)
        return worker


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, skill_id: UUID) -> Skill | None:
        return await self.session.get(Skill, skill_id)

    async def get_by_slug(self, slug: str) -> Skill | None:
        return await self.session.scalar(select(Skill).where(Skill.slug == slug))

    async def search(self, q: str | None, limit: int) -> list[Skill]:
        stmt = select(Skill).order_by(Skill.slug).limit(limit)
        if q:
            # autoescape: '%' and '_' in the term match literally.
            stmt = stmt.where(
                or_(
                    Skill.slug.icontains(q, autoescape=True),
                    func.jsonb_extract_path_text(Skill.name_i18n, "en").icontains(
                        q, autoescape=True
                    ),
                    func.jsonb_extract_path_text(Skill.name_i18n, "fr").icontains(
                        q, autoescape=True
                    ),
                )
            )
        return list((await self.session.scalars(stmt)).all())

    def add(self, skill: Skill) -> Skill:
        self.session.add(skill)
        return skill


class SkillClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_worker(self, worker_id: UUID) -> list[tuple[SkillClaim, Skill]]:
        rows = await self.session.execute(
            select(SkillClaim, Skill)
            .join(Skill, Skill.id == SkillClaim.skill_id)
            .where(SkillClaim.worker_id == worker_id)
            .order_by(Skill.slug)
        )
        return [(claim, skill) for claim, skill in rows.all()]

    async def get(self, worker_id: UUID, skill_id: UUID) -> SkillClaim | None:
        return await self.session.scalar(
            select(SkillClaim).where(
                SkillClaim.worker_id == worker_id, SkillClaim.skill_id == skill_id
            )
        )

    def add(self, claim: SkillClaim) -> SkillClaim:
        self.session.add(claim)
        return claim

    async def delete(self, claim: SkillClaim) -> None:
        await self.session.delete(claim)
```

`backend/app/modules/passport/schemas.py`:

```python
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.i18n import Locale
from app.core.outbox.events import DomainEvent
from app.modules.passport.enums import VerificationStatus


class SkillCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    name_i18n: dict[Locale, str]

    @field_validator("name_i18n")
    @classmethod
    def _english_name_required(cls, value: dict[Locale, str]) -> dict[Locale, str]:
        if "en" not in value:
            raise ValueError("an English name is required")
        if any(not name.strip() or len(name) > 120 for name in value.values()):
            raise ValueError("names must be 1-120 characters")
        return value


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name_i18n: dict[str, str]


class SkillClaimCreate(BaseModel):
    skill_id: UUID


class WorkerSkill(BaseModel):
    skill_id: UUID
    slug: str
    verification_status: VerificationStatus


class WorkerUpdated(DomainEvent):
    event_type: ClassVar[str] = "passport.worker_updated"
    fields: list[str]
```

`backend/app/modules/passport/dependencies.py`:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.context import Actor
from app.core.errors import Forbidden
from app.modules.identity.service import Permission, require_permission


@dataclass(frozen=True, slots=True)
class WorkerActor:
    """A worker acting on their own passport."""

    actor: Actor
    worker_id: UUID


def _worker_self(permission: Permission) -> Callable[..., Awaitable[WorkerActor]]:
    async def dependency(
        actor: Annotated[Actor, Depends(require_permission(permission))],
    ) -> WorkerActor:
        if actor.worker_id is None:
            raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
        return WorkerActor(actor=actor, worker_id=actor.worker_id)

    return dependency


WorkerReader = Annotated[WorkerActor, Depends(_worker_self(Permission.WORKER_READ_SELF))]
WorkerEditor = Annotated[WorkerActor, Depends(_worker_self(Permission.WORKER_UPDATE_SELF))]
```

`backend/app/modules/passport/skills.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.passport.dependencies import WorkerActor
from app.modules.passport.enums import ClaimSource, VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.passport.repository import SkillClaimRepository, SkillRepository
from app.modules.passport.schemas import SkillCreate, WorkerSkill, WorkerUpdated


class SkillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skills = SkillRepository(session)

    async def create(self, actor: Actor, data: SkillCreate) -> Skill:
        if await self.skills.get_by_slug(data.slug) is not None:
            raise Conflict("A skill with this slug exists", code="skill_slug_taken")
        names = {str(locale): name.strip() for locale, name in data.name_i18n.items()}
        skill = self.skills.add(Skill(slug=data.slug, name_i18n=names))
        await self.session.flush()
        await write_audit(
            self.session,
            actor=actor,
            action="skill.created",
            target_type="skill",
            target_id=skill.id,
            after={"slug": skill.slug, "name_i18n": skill.name_i18n},
        )
        return skill

    async def search(self, q: str | None, limit: int) -> list[Skill]:
        return await self.skills.search(q, limit)


class ClaimService:
    """Self-reported claims. Verification is earned through reviews (Plan 3),
    never set here (FR-2.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skills = SkillRepository(session)
        self.claims = SkillClaimRepository(session)

    async def claim(self, who: WorkerActor, skill_id: UUID) -> WorkerSkill:
        skill = await self.skills.get(skill_id)
        if skill is None:
            raise NotFound("Skill not found", code="skill_not_found")
        if await self.claims.get(who.worker_id, skill_id) is not None:
            raise Conflict("You already list this skill", code="skill_already_claimed")
        claim = self.claims.add(
            SkillClaim(
                worker_id=who.worker_id,
                skill_id=skill_id,
                verification_status=VerificationStatus.SELF_REPORTED,
                source=ClaimSource.SELF,
            )
        )
        await emit_event(self.session, WorkerUpdated(aggregate_id=who.worker_id, fields=["skills"]))
        return WorkerSkill(
            skill_id=skill.id, slug=skill.slug, verification_status=claim.verification_status
        )

    async def remove(self, who: WorkerActor, skill_id: UUID) -> None:
        claim = await self.claims.get(who.worker_id, skill_id)
        if claim is None:
            raise NotFound("You do not list this skill", code="claim_not_found")
        if claim.verification_status is VerificationStatus.BONARDA_VERIFIED:
            raise Conflict(
                "Verified skills are backed by reviews and cannot be removed",
                code="skill_verified_locked",
            )
        await self.claims.delete(claim)
        await emit_event(self.session, WorkerUpdated(aggregate_id=who.worker_id, fields=["skills"]))
```

`backend/app/modules/passport/router.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.identity.service import CurrentActor, Permission, require_permission
from app.modules.passport.dependencies import WorkerEditor
from app.modules.passport.schemas import SkillClaimCreate, SkillCreate, SkillRead, WorkerSkill
from app.modules.passport.skills import ClaimService, SkillService

router = APIRouter(prefix="/api/v1", tags=["passport"])

SkillManager = Annotated[Actor, Depends(require_permission(Permission.SKILL_MANAGE))]


@router.get("/skills")
async def search_skills(
    actor: CurrentActor,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SkillRead]:
    skills = await SkillService(session).search(q, limit)
    return [SkillRead.model_validate(s) for s in skills]


@router.post("/skills", status_code=201)
async def create_skill(body: SkillCreate, actor: SkillManager, session: SessionDep) -> SkillRead:
    return SkillRead.model_validate(await SkillService(session).create(actor, body))


@router.post("/workers/me/skills", status_code=201)
async def claim_skill(
    body: SkillClaimCreate, who: WorkerEditor, session: SessionDep
) -> WorkerSkill:
    return await ClaimService(session).claim(who, body.skill_id)


@router.delete("/workers/me/skills/{skill_id}", status_code=204)
async def remove_skill_claim(skill_id: UUID, who: WorkerEditor, session: SessionDep) -> None:
    await ClaimService(session).remove(who, skill_id)
```

`backend/app/modules/passport/service.py`:

```python
"""Public interface of the passport module. Other modules import from here
(and from schemas) only."""

from app.modules.passport.enums import (
    AvailabilityStatus,
    ConsentPurpose,
    OnboardingState,
    StandingTier,
    VerificationStatus,
    WorkerStatus,
    WorkerType,
)

__all__ = [
    "AvailabilityStatus",
    "ConsentPurpose",
    "OnboardingState",
    "StandingTier",
    "VerificationStatus",
    "WorkerStatus",
    "WorkerType",
]
```

In `backend/app/main.py`, import `from app.modules.passport.router import router as passport_router` and add `app.include_router(passport_router)` after the identity router.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/passport/test_skills.py tests/unit/identity/test_permissions.py -v`
Expected: all pass (the permissions docs-freshness test confirms the regenerated `docs/permissions.md`).

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
cd ..
git add backend/app backend/tests docs/permissions.md
git commit -m "feat(passport): skills taxonomy and self-reported skill claims"
cd backend
```

---

### Task 6: Worker profile — read, update, onboarding

**Files:**
- Create: `backend/app/modules/passport/profile.py`
- Modify: `backend/app/modules/passport/schemas.py`, `backend/app/modules/passport/router.py`
- Test: `backend/tests/api/passport/test_worker_profile.py`

**Interfaces:**
- Consumes: `account_contact`, `Visibility`, `VisibilityPolicy`, `require_visibility` (identity.service); `WorkerActor`, `WorkerReader`, `WorkerEditor`; repositories from Task 5.
- Produces:
  - Schemas `WorkerSummary` (`view: "summary"`), `WorkerDetail` (`view: "detail"`), `WorkerSelf` (`view: "self"`), union `WorkerView` discriminated on `view`; `WorkerUpdate`.
  - `ProfileService(session)`: `view(actor, worker_id, level) -> WorkerSummary | WorkerDetail | WorkerSelf`, `update_self(who, data) -> WorkerSelf`, `complete_onboarding(who) -> WorkerSelf`.
  - Error codes `worker_not_found` (404), `onboarding_incomplete` (409).
  - Routes: `GET /api/v1/workers/me`, `PATCH /api/v1/workers/me`, `POST /api/v1/workers/me/onboarding/complete`, `GET /api/v1/workers/{worker_id}` (guarded by `require_visibility(Visibility.SUMMARY)`).

Field sets (spec §7.1): **summary** is what a PM sees on a search card — id, name, type, status, region, base location, availability, tier and skills. **detail** adds languages, onboarding state, dormant-since and created-at. **self** adds the worker's own email and locale.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/passport/test_worker_profile.py`:

```python
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.identity.service import Visibility, VisibilityPolicy
from app.modules.passport.enums import OnboardingState
from app.modules.passport.models import Skill, SkillClaim
from tests.support import bearer, make_user, make_worker


async def _add_skill_claim(session: AsyncSession, worker_id: UUID) -> Skill:
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.flush()
    session.add(SkillClaim(worker_id=worker_id, skill_id=skill.id))
    await session.commit()
    return skill


async def test_worker_reads_their_own_passport(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session, email="kofi@example.com", locale="fr")
    await _add_skill_claim(session, worker.id)

    response = await client.get("/api/v1/workers/me", headers=bearer(settings, account))

    body = response.json()
    assert response.status_code == 200
    assert (body["view"], body["id"], body["email"], body["locale"]) == (
        "self", str(worker.id), "kofi@example.com", "fr"
    )
    assert [s["slug"] for s in body["skills"]] == ["data-analysis"]


async def test_people_ops_sees_detail_without_contact_details(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(f"/api/v1/workers/{worker.id}", headers=bearer(settings, ops))

    body = response.json()
    assert body["view"] == "detail"
    assert "languages" in body
    assert "email" not in body


async def test_summary_viewer_gets_only_the_search_card(
    app: FastAPI, client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    pm = await make_user(session, role=UserRole.PM)

    async def summary(s: AsyncSession, a: Actor, w: UUID) -> Visibility:
        return Visibility.SUMMARY

    app.state.visibility_policy = VisibilityPolicy([summary])

    response = await client.get(f"/api/v1/workers/{worker.id}", headers=bearer(settings, pm))

    body = response.json()
    assert body["view"] == "summary"
    assert "languages" not in body
    assert "onboarding_state" not in body


@pytest.mark.parametrize("role", [UserRole.PM, UserRole.FINANCE])
async def test_staff_without_visibility_get_404(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    worker, _ = await make_worker(session)
    user = await make_user(session, role=role)

    response = await client.get(f"/api/v1/workers/{worker.id}", headers=bearer(settings, user))

    assert response.status_code == 404
    assert response.json()["code"] == "worker_not_found"


async def test_unknown_worker_is_404_even_for_people_ops(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(f"/api/v1/workers/{uuid4()}", headers=bearer(settings, ops))

    assert response.json()["code"] == "worker_not_found"


async def test_worker_updates_their_profile(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)

    response = await client.patch(
        "/api/v1/workers/me",
        json={
            "base_location": "Accra",
            "languages": ["en", "fr", "en"],
            "availability_status": "available_from",
            "available_from": "2026-11-01",
        },
        headers=bearer(settings, account),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["languages"] == ["en", "fr"]  # de-duplicated, order kept
    assert (body["availability_status"], body["available_from"]) == (
        "available_from", "2026-11-01"
    )
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "passport.worker_updated"
    assert event.payload["fields"] == [
        "availability_status", "available_from", "base_location", "languages"
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"languages": ["EN"]},
        {"availability_status": "available_from"},
        {"available_from": "2026-11-01"},
        {"full_name": None},
        {"worker_id": str(uuid4())},
    ],
)
async def test_invalid_profile_updates_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, body: dict[str, object]
) -> None:
    _, account = await make_worker(session)

    response = await client.patch(
        "/api/v1/workers/me", json=body, headers=bearer(settings, account)
    )

    assert response.status_code == 422


async def test_becoming_available_clears_the_available_from_date(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "available_from", "available_from": "2026-11-01"},
        headers=headers,
    )

    response = await client.patch(
        "/api/v1/workers/me", json={"availability_status": "available"}, headers=headers
    )

    assert response.json()["available_from"] is None


async def test_onboarding_requires_location_languages_and_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session, onboarding_state=OnboardingState.INVITED)
    headers = bearer(settings, account)

    early = await client.post("/api/v1/workers/me/onboarding/complete", headers=headers)
    await client.patch(
        "/api/v1/workers/me",
        json={"base_location": "Accra", "languages": ["en"]},
        headers=headers,
    )
    await _add_skill_claim(session, worker.id)
    done = await client.post("/api/v1/workers/me/onboarding/complete", headers=headers)
    again = await client.post("/api/v1/workers/me/onboarding/complete", headers=headers)

    assert early.status_code == 409
    assert early.json()["code"] == "onboarding_incomplete"
    assert "base_location" in early.json()["detail"]
    assert done.json()["onboarding_state"] == "profile_complete"
    assert again.status_code == 200
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions.count("worker.onboarding_completed") == 1
```

The `{"worker_id": ...}` case checks that the update schema forbids unknown fields — a worker can never retarget an update at another passport.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/passport/test_worker_profile.py -v`
Expected: FAIL — 404/405 responses (routes don't exist).

- [ ] **Step 3: Implement**

Append to `backend/app/modules/passport/schemas.py` (add imports `from datetime import date, datetime`, `from typing import Annotated, Literal, Self`, `from pydantic import StringConstraints, model_validator`, and the enums `AvailabilityStatus, OnboardingState, StandingTier, WorkerStatus, WorkerType`):

```python
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]


class _SummaryFields(BaseModel):
    id: UUID
    full_name: str
    worker_type: WorkerType
    status: WorkerStatus
    data_region: str
    base_location: str | None
    availability_status: AvailabilityStatus
    available_from: date | None
    standing_tier: StandingTier
    skills: list[WorkerSkill]


class _DetailFields(_SummaryFields):
    languages: list[str]
    onboarding_state: OnboardingState
    dormant_since: date | None
    created_at: datetime


class WorkerSummary(_SummaryFields):
    view: Literal["summary"] = "summary"


class WorkerDetail(_DetailFields):
    view: Literal["detail"] = "detail"


class WorkerSelf(_DetailFields):
    view: Literal["self"] = "self"
    email: str
    locale: str


WorkerView = Annotated[WorkerSummary | WorkerDetail | WorkerSelf, Field(discriminator="view")]


class WorkerUpdate(BaseModel):
    """Self-editable fields only (FR-1.5). Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_location: str | None = Field(default=None, max_length=120)
    languages: list[LanguageCode] | None = Field(default=None, max_length=10)
    availability_status: AvailabilityStatus | None = None
    available_from: date | None = None

    @field_validator("languages")
    @classmethod
    def _dedupe(cls, value: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(value)) if value is not None else None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if "full_name" in self.model_fields_set and self.full_name is None:
            raise ValueError("full_name cannot be cleared")
        wants_date = self.availability_status is AvailabilityStatus.AVAILABLE_FROM
        if wants_date and self.available_from is None:
            raise ValueError("available_from is required with availability_status=available_from")
        if self.available_from is not None and not wants_date:
            raise ValueError("available_from needs availability_status=available_from")
        return self
```

`backend/app/modules/passport/profile.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.identity.service import Visibility, account_contact
from app.modules.passport.dependencies import WorkerActor
from app.modules.passport.enums import AvailabilityStatus, OnboardingState
from app.modules.passport.models import Worker
from app.modules.passport.repository import SkillClaimRepository, WorkerRepository
from app.modules.passport.schemas import (
    WorkerDetail,
    WorkerSelf,
    WorkerSkill,
    WorkerSummary,
    WorkerUpdate,
    WorkerUpdated,
)


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workers = WorkerRepository(session)
        self.claims = SkillClaimRepository(session)

    async def _worker(self, worker_id: UUID) -> Worker:
        worker = await self.workers.get(worker_id)
        if worker is None:
            raise NotFound("Worker not found", code="worker_not_found")
        return worker

    async def _skills(self, worker_id: UUID) -> list[WorkerSkill]:
        return [
            WorkerSkill(
                skill_id=skill.id, slug=skill.slug, verification_status=claim.verification_status
            )
            for claim, skill in await self.claims.list_for_worker(worker_id)
        ]

    async def view(
        self, actor: Actor, worker_id: UUID, level: Visibility
    ) -> WorkerSummary | WorkerDetail | WorkerSelf:
        worker = await self._worker(worker_id)
        summary: dict[str, Any] = {
            "id": worker.id,
            "full_name": worker.full_name,
            "worker_type": worker.worker_type,
            "status": worker.status,
            "data_region": worker.data_region,
            "base_location": worker.base_location,
            "availability_status": worker.availability_status,
            "available_from": worker.available_from,
            "standing_tier": worker.standing_tier,
            "skills": await self._skills(worker.id),
        }
        if level is Visibility.SUMMARY:
            return WorkerSummary(**summary)
        detail = summary | {
            "languages": worker.languages,
            "onboarding_state": worker.onboarding_state,
            "dormant_since": worker.dormant_since,
            "created_at": worker.created_at,
        }
        if level is Visibility.SELF:
            contact = await account_contact(self.session, actor.user_id)
            return WorkerSelf(**detail, email=contact.email, locale=contact.locale)
        return WorkerDetail(**detail)

    async def view_self(self, who: WorkerActor) -> WorkerSelf:
        view = await self.view(who.actor, who.worker_id, Visibility.SELF)
        assert isinstance(view, WorkerSelf)
        return view

    async def update_self(self, who: WorkerActor, data: WorkerUpdate) -> WorkerSelf:
        worker = await self._worker(who.worker_id)
        changes = data.model_dump(exclude_unset=True)
        status = changes.get("availability_status")
        if status is not None and status is not AvailabilityStatus.AVAILABLE_FROM:
            changes["available_from"] = None
        for field, value in changes.items():
            setattr(worker, field, value)
        if changes:
            await emit_event(
                self.session, WorkerUpdated(aggregate_id=worker.id, fields=sorted(changes))
            )
        return await self.view_self(who)

    async def complete_onboarding(self, who: WorkerActor) -> WorkerSelf:
        """Gates first-time engagements (FR-5.1). Idempotent."""
        worker = await self._worker(who.worker_id)
        if worker.onboarding_state is not OnboardingState.PROFILE_COMPLETE:
            missing = []
            if not worker.base_location:
                missing.append("base_location")
            if not worker.languages:
                missing.append("languages")
            if not await self.claims.list_for_worker(worker.id):
                missing.append("skills")
            if missing:
                raise Conflict(
                    f"Complete your profile first: {', '.join(missing)}",
                    code="onboarding_incomplete",
                )
            worker.onboarding_state = OnboardingState.PROFILE_COMPLETE
            await write_audit(
                self.session,
                actor=who.actor,
                action="worker.onboarding_completed",
                target_type="worker",
                target_id=worker.id,
            )
            await emit_event(
                self.session, WorkerUpdated(aggregate_id=worker.id, fields=["onboarding_state"])
            )
        return await self.view_self(who)
```

Add to `backend/app/modules/passport/router.py` (imports: `from app.modules.identity.service import Visibility, require_visibility`; `from app.modules.passport.dependencies import WorkerReader`; `from app.modules.passport.profile import ProfileService`; schemas `WorkerSelf, WorkerUpdate, WorkerView`). The `/workers/me` routes must be declared before `/workers/{worker_id}`:

```python
@router.get("/workers/me")
async def read_my_passport(who: WorkerReader, session: SessionDep) -> WorkerSelf:
    return await ProfileService(session).view_self(who)


@router.patch("/workers/me")
async def update_my_passport(
    body: WorkerUpdate, who: WorkerEditor, session: SessionDep
) -> WorkerSelf:
    return await ProfileService(session).update_self(who, body)


@router.post("/workers/me/onboarding/complete")
async def complete_onboarding(who: WorkerEditor, session: SessionDep) -> WorkerSelf:
    return await ProfileService(session).complete_onboarding(who)


@router.get("/workers/{worker_id}")
async def read_worker(
    worker_id: UUID,
    actor: CurrentActor,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> WorkerView:
    return await ProfileService(session).view(actor, worker_id, level)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/passport tests/api/test_visibility_guard.py -v`
Expected: all pass (the guard test confirms `GET /workers/{worker_id}` carries the visibility dependency).

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(passport): worker profile views, self-service updates and onboarding"
```

---

### Task 7: Consents

**Files:**
- Create: `backend/app/modules/passport/consents.py`
- Modify: `backend/app/modules/passport/repository.py`, `backend/app/modules/passport/schemas.py`, `backend/app/modules/passport/router.py`
- Test: `backend/tests/api/passport/test_consents.py`

**Interfaces:**
- Produces: `ConsentRepository(session)` with `list_for_worker`, `get(worker_id, purpose)`, `add`; schemas `ConsentRead(purpose, granted, legal_basis, granted_at, withdrawn_at)`, `ConsentUpdate(granted: bool)`, event `ConsentChanged(aggregate_id, purpose, granted)` with `event_type = "passport.consent_changed"`; `ConsentService(session)` with `list_for(worker_id) -> list[ConsentRead]`, `set(who, purpose, granted) -> ConsentRead`; `LEGAL_BASIS_CONSENT = "consent"`; routes `GET /api/v1/workers/me/consents`, `PUT /api/v1/workers/me/consents/{purpose}`.

Consent is privacy-significant (NFR-4.3), so every real change is audited. A worker who has never granted a purpose has no row; the list shows it as not granted.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/passport/test_consents.py`:

```python
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from tests.support import bearer, make_user, make_worker

URL = "/api/v1/workers/me/consents"


async def test_consents_default_to_not_granted(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)

    response = await client.get(URL, headers=bearer(settings, account))

    assert [(c["purpose"], c["granted"], c["legal_basis"]) for c in response.json()] == [
        ("cross_region_matching", False, None),
        ("external_prefill", False, None),
    ]


async def test_granting_consent_is_audited_and_published(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)

    response = await client.put(
        f"{URL}/cross_region_matching", json={"granted": True}, headers=bearer(settings, account)
    )

    body = response.json()
    assert (body["granted"], body["legal_basis"]) == (True, "consent")
    assert body["granted_at"] is not None
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.target_id) == ("consent.granted", worker.id)
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.payload == {
        "aggregate_id": str(worker.id), "purpose": "cross_region_matching", "granted": True,
    }


async def test_withdrawing_consent_records_when(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)

    response = await client.put(
        f"{URL}/cross_region_matching", json={"granted": False}, headers=headers
    )

    body = response.json()
    assert body["granted"] is False
    assert body["withdrawn_at"] is not None
    actions = (await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["consent.granted", "consent.withdrawn"]


async def test_setting_the_current_value_changes_nothing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)

    await client.put(f"{URL}/external_prefill", json={"granted": False}, headers=headers)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)

    assert len((await session.scalars(select(AuditLog))).all()) == 1
    assert len((await session.scalars(select(OutboxEvent))).all()) == 1


async def test_unknown_purpose_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)

    response = await client.put(
        f"{URL}/marketing", json={"granted": True}, headers=bearer(settings, account)
    )

    assert response.status_code == 422


async def test_staff_have_no_consents_endpoint(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.get(URL, headers=bearer(settings, pm))

    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/passport/test_consents.py -v`
Expected: FAIL — 404/405 responses.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/passport/repository.py` (import `Consent` and `ConsentPurpose`):

```python
class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_worker(self, worker_id: UUID) -> list[Consent]:
        return list(
            (await self.session.scalars(select(Consent).where(Consent.worker_id == worker_id))).all()
        )

    async def get(self, worker_id: UUID, purpose: ConsentPurpose) -> Consent | None:
        return await self.session.scalar(
            select(Consent).where(Consent.worker_id == worker_id, Consent.purpose == purpose)
        )

    def add(self, consent: Consent) -> Consent:
        self.session.add(consent)
        return consent
```

Append to `backend/app/modules/passport/schemas.py` (import `ConsentPurpose`):

```python
class ConsentRead(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    legal_basis: str | None
    granted_at: datetime | None
    withdrawn_at: datetime | None


class ConsentUpdate(BaseModel):
    granted: bool


class ConsentChanged(DomainEvent):
    event_type: ClassVar[str] = "passport.consent_changed"
    purpose: ConsentPurpose
    granted: bool
```

`backend/app/modules/passport/consents.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.passport.dependencies import WorkerActor
from app.modules.passport.enums import ConsentPurpose
from app.modules.passport.models import Consent
from app.modules.passport.repository import ConsentRepository
from app.modules.passport.schemas import ConsentChanged, ConsentRead

# GDPR Art. 6(1)(a) / Ghana DPA: processing based on the worker's own consent.
LEGAL_BASIS_CONSENT = "consent"


def _read(purpose: ConsentPurpose, consent: Consent | None) -> ConsentRead:
    if consent is None:
        return ConsentRead(
            purpose=purpose, granted=False, legal_basis=None, granted_at=None, withdrawn_at=None
        )
    return ConsentRead(
        purpose=purpose,
        granted=consent.granted,
        legal_basis=consent.legal_basis,
        granted_at=consent.granted_at,
        withdrawn_at=consent.withdrawn_at,
    )


class ConsentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.consents = ConsentRepository(session)

    async def list_for(self, worker_id: UUID) -> list[ConsentRead]:
        existing = {c.purpose: c for c in await self.consents.list_for_worker(worker_id)}
        return [_read(purpose, existing.get(purpose)) for purpose in ConsentPurpose]

    async def set(self, who: WorkerActor, purpose: ConsentPurpose, granted: bool) -> ConsentRead:
        consent = await self.consents.get(who.worker_id, purpose)
        current = consent.granted if consent is not None else False
        if granted == current:
            return _read(purpose, consent)
        now = utcnow()
        if consent is None:
            consent = self.consents.add(
                Consent(
                    worker_id=who.worker_id,
                    purpose=purpose,
                    granted=granted,
                    legal_basis=LEGAL_BASIS_CONSENT,
                )
            )
        consent.granted = granted
        if granted:
            consent.granted_at = now
            consent.withdrawn_at = None
        else:
            consent.withdrawn_at = now
        await write_audit(
            self.session,
            actor=who.actor,
            action="consent.granted" if granted else "consent.withdrawn",
            target_type="worker",
            target_id=who.worker_id,
            after={"purpose": purpose.value, "granted": granted},
        )
        await emit_event(
            self.session,
            ConsentChanged(aggregate_id=who.worker_id, purpose=purpose, granted=granted),
        )
        return _read(purpose, consent)
```

Add to `backend/app/modules/passport/router.py` (imports `ConsentPurpose` from `app.modules.passport.enums`, `ConsentRead, ConsentUpdate` from schemas, `ConsentService` from `app.modules.passport.consents`), declared before the `/workers/{worker_id}` route:

```python
@router.get("/workers/me/consents")
async def list_my_consents(who: WorkerReader, session: SessionDep) -> list[ConsentRead]:
    return await ConsentService(session).list_for(who.worker_id)


@router.put("/workers/me/consents/{purpose}")
async def set_my_consent(
    purpose: ConsentPurpose, body: ConsentUpdate, who: WorkerEditor, session: SessionDep
) -> ConsentRead:
    return await ConsentService(session).set(who, purpose, body.granted)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/passport/test_consents.py -v`
Expected: 6 passed.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(passport): worker consents with audit and change events"
```

---

### Task 8: PM invitations for first-time workers

**Files:**
- Create: `backend/app/modules/passport/invitations.py`
- Modify: `backend/app/core/i18n.py`, `backend/app/modules/identity/accounts.py`, `backend/app/modules/identity/schemas.py`, `backend/app/modules/identity/magic_link.py`, `backend/app/modules/identity/service.py`, `backend/app/modules/passport/schemas.py`, `backend/app/modules/passport/router.py`
- Test: `backend/tests/api/passport/test_invitations.py`

**Interfaces:**
- Consumes: `request_sign_in_link`, `send_magic_link` (Task 2); `WorkerRepository`.
- Produces:
  - `SignInPurpose = Literal["sign_in", "invitation"]`; i18n keys `invitation.subject`, `invitation.body` (en, fr); `_TEMPLATES["invitation"] = "invitation"`.
  - `identity.service.provision_worker_account(session, *, actor, email, worker_id, locale) -> UUID` — raises `409 email_in_use` if any account has the email.
  - Schemas `InvitationCreate(email, full_name, worker_type, data_region, locale)`, `InvitationRead(worker_id, email, onboarding_state)`, event `WorkerInvited(aggregate_id, invited_by_id)` with `event_type = "passport.worker_invited"`.
  - `InvitationService(session).invite(actor, data) -> InvitationRead`.
  - Route `POST /api/v1/workers/invitations` (201, permission `WORKER_INVITE`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/passport/test_invitations.py`:

```python
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

    signed_in = await client.post(
        "/api/v1/auth/magic-link/verify", json={"token": mailer.token()}
    )
    token = signed_in.json()["access_token"]
    passport = await client.get(
        "/api/v1/workers/me", headers={"Authorization": f"Bearer {token}"}
    )

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/passport/test_invitations.py -v`
Expected: FAIL — 405 on `POST /api/v1/workers/invitations` (only `GET /workers/{worker_id}` matches the path).

- [ ] **Step 3: Implement**

In `backend/app/core/i18n.py`, add to the `"en"` catalog:

```python
        "invitation.subject": "You're invited to Bonarda Works",
        "invitation.body": (
            "Bonarda Works has created a passport for you. Use this link to sign in "
            "and complete your profile. It works once and expires in {minutes} minutes:"
            "\n\n{link}\n\n"
            "If it has expired, request a new link at {sign_in_url}."
        ),
```

and to the `"fr"` catalog:

```python
        "invitation.subject": "Vous êtes invité(e) sur Bonarda Works",
        "invitation.body": (
            "Bonarda Works a créé un passeport pour vous. Utilisez ce lien pour vous "
            "connecter et compléter votre profil. Il ne fonctionne qu'une fois et expire "
            "dans {minutes} minutes :\n\n{link}\n\n"
            "S'il a expiré, demandez un nouveau lien sur {sign_in_url}."
        ),
```

In `backend/app/modules/identity/schemas.py`, change `SignInPurpose = Literal["sign_in"]` to `SignInPurpose = Literal["sign_in", "invitation"]`.

In `backend/app/modules/identity/magic_link.py`, change `_TEMPLATES` to `{"sign_in": "magic_link", "invitation": "invitation"}` and update its comment to "i18n key prefix per purpose."

Append to `backend/app/modules/identity/accounts.py` (imports: `from sqlalchemy.exc import IntegrityError`, `from app.core.audit.writer import write_audit`, `from app.core.context import Actor`, `from app.core.enums import AuthProvider, UserRole`, `from app.core.errors import Conflict`, `from app.modules.identity.models import UserAccount`):

```python
async def provision_worker_account(
    session: AsyncSession, *, actor: Actor, email: str, worker_id: UUID, locale: str
) -> UUID:
    """Creates the sign-in account a worker's passport hangs off (FR-9.2, FR-9.6)."""
    users = UserRepository(session)
    try:
        async with session.begin_nested():
            user = users.add(
                UserAccount(
                    email=email,
                    role=UserRole.WORKER,
                    auth_provider=AuthProvider.MAGIC_LINK,
                    worker_id=worker_id,
                    locale=locale,
                )
            )
            await session.flush()
    except IntegrityError as exc:
        raise Conflict("An account with this email already exists", code="email_in_use") from exc
    await write_audit(
        session,
        actor=actor,
        action="user.provisioned",
        target_type="user_account",
        target_id=user.id,
        after={"email": user.email, "role": UserRole.WORKER.value},
    )
    return user.id
```

Add `provision_worker_account` to the `accounts` import and to `__all__` in `backend/app/modules/identity/service.py`.

Append to `backend/app/modules/passport/schemas.py` (imports `EmailStr` from pydantic, `Locale` already imported, `WorkerType`, `OnboardingState` already imported):

```python
class InvitationCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    worker_type: WorkerType
    data_region: str = Field(pattern=r"^[A-Z]{2,8}$")
    locale: Locale = "en"


class InvitationRead(BaseModel):
    worker_id: UUID
    email: str
    onboarding_state: OnboardingState


class WorkerInvited(DomainEvent):
    event_type: ClassVar[str] = "passport.worker_invited"
    invited_by_id: UUID
```

`backend/app/modules/passport/invitations.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.outbox.writer import emit_event
from app.modules.identity.service import provision_worker_account, request_sign_in_link
from app.modules.passport.enums import OnboardingState, WorkerStatus
from app.modules.passport.models import Worker
from app.modules.passport.repository import WorkerRepository
from app.modules.passport.schemas import InvitationCreate, InvitationRead, WorkerInvited


class InvitationService:
    """Standard onboarding path for first-time workers (FR-5.1): the PM creates
    the passport and account; the worker completes the profile themselves."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workers = WorkerRepository(session)

    async def invite(self, actor: Actor, data: InvitationCreate) -> InvitationRead:
        email = data.email.strip().lower()
        worker = self.workers.add(
            Worker(
                full_name=data.full_name.strip(),
                worker_type=data.worker_type,
                data_region=data.data_region,
                status=WorkerStatus.DORMANT,
                onboarding_state=OnboardingState.INVITED,
            )
        )
        await self.session.flush()
        # Raises 409 email_in_use; the request's rollback then removes the worker row.
        user_id = await provision_worker_account(
            self.session, actor=actor, email=email, worker_id=worker.id, locale=data.locale
        )
        await write_audit(
            self.session,
            actor=actor,
            action="worker.invited",
            target_type="worker",
            target_id=worker.id,
            after={"email": email, "data_region": worker.data_region},
        )
        await emit_event(
            self.session, WorkerInvited(aggregate_id=worker.id, invited_by_id=actor.user_id)
        )
        await request_sign_in_link(self.session, user_id, purpose="invitation")
        return InvitationRead(
            worker_id=worker.id, email=email, onboarding_state=worker.onboarding_state
        )
```

Add to `backend/app/modules/passport/router.py` (imports `InvitationCreate, InvitationRead` and `InvitationService`), declared before `GET /workers/{worker_id}`:

```python
Inviter = Annotated[Actor, Depends(require_permission(Permission.WORKER_INVITE))]


@router.post("/workers/invitations", status_code=201)
async def invite_worker(
    body: InvitationCreate, actor: Inviter, session: SessionDep
) -> InvitationRead:
    return await InvitationService(session).invite(actor, body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/passport tests/api/identity tests/unit/test_i18n.py -v`
Expected: all pass (the i18n key-parity test confirms both locales define the invitation templates).

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(passport): PM invitations with localized invitation email"
```

---

### Task 9: Body-addressed worker guard, docs and final verification

**Files:**
- Modify: `backend/app/modules/identity/visibility.py`, `backend/tests/api/test_visibility_guard.py`, `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`, `PROJECT_STRUCTURE.md`

**Interfaces:**
- Produces: `unguarded_worker_routes(app)` also reports any route whose request body model has a `worker_id` field (guarded or not — workers must be addressed in the path).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/test_visibility_guard.py` (import `BaseModel` from pydantic):

```python
class _Reactivation(BaseModel):
    worker_id: UUID
    project_id: UUID


class _Grant(BaseModel):
    scoped_worker_id: UUID


def test_worker_id_in_a_request_body_is_always_reported() -> None:
    app = FastAPI()

    @app.post("/reactivations")
    async def body_addressed(body: _Reactivation) -> None:
        return None

    @app.post("/grants")
    async def differently_named(body: _Grant) -> None:
        return None

    assert unguarded_worker_routes(app) == ["/reactivations"]
```

Run: `pytest tests/api/test_visibility_guard.py -v`
Expected: the new test FAILS (`[] != ['/reactivations']`).

- [ ] **Step 2: Implement**

In `backend/app/modules/identity/visibility.py`, add `from pydantic import BaseModel` and replace `unguarded_worker_routes` with:

```python
def _body_field_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    for param in get_flat_dependant(route.dependant).body_params:
        annotation = param.field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= set(annotation.model_fields)
        else:
            names.add(param.name)
    return names


def unguarded_worker_routes(app: FastAPI) -> list[str]:
    """Routes that could expose a worker without the visibility check: a
    `worker_id` path/query parameter without require_visibility, or a
    `worker_id` anywhere in a request body (address workers in the path)."""
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        flat = get_flat_dependant(route.dependant)
        params = {p.name for p in flat.path_params + flat.query_params}
        unguarded_param = "worker_id" in params and not _has_guard(route.dependant)
        if unguarded_param or "worker_id" in _body_field_names(route):
            offenders.append(route.path)
    return offenders
```

Run: `pytest tests/api/test_visibility_guard.py -v`
Expected: 3 passed, including `test_application_has_no_unguarded_worker_routes`.

- [ ] **Step 3: Update the roadmap**

In `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`:
- Replace the Plan 2 row with two rows:

```markdown
| 2A | `2026-09-23-bonarda-02a-worker-passport.md` | `passport` (workers, skills taxonomy and claims, profile views, onboarding, consents, PM invitations), SMTP mailer, sign-in mail sent by the worker, per-account locale, Plan 1 identity carry-forward fixes | 1 | Written |
| 2B | `…-02b-engagements.md` | `engagements` (projects, staffing, first-time engagements, reactivation prefill and create, contracts via fake e-sign, e-sign webhook, payroll signal, completion, feedback, stuck detector), e-sign/payroll adapters, PM visibility sources, `AccessRevoked` → end `project_staff` | 2A | Not written |
```

- Delete the carry-forward rows for Plan 2 that this plan completed (FKs and grant validation; role authority; SCIM remove; magic-link role re-check and off-request-path mail) and the "3 (before any body-addressed worker route)" row. Change the remaining Plan 2 row (`AccessRevoked` handler ends `project_staff`) to Plan 2B.
- Append a section:

```markdown
## Implementation deviations from the spec (recorded as they happen)

| Plan | Deviation | Reason |
|---|---|---|
| 1 | Refresh cookie path is `/api/v1/auth`, not `/api/v1/auth/refresh` | Logout must receive the cookie too |
| 2A | `workers` has no `email`/`locale`; both live on `user_accounts` (locale for every account) | One source of truth; PMs need a locale too (NFR-8.2) |
| 2A | Worker-scoped routes put the worker in the path (`/workers/{worker_id}/…`); request bodies never carry `worker_id` | Every worker route passes through the visibility guard, enforced in CI |
| 2A | Staff roles come only from the IdP (SCIM push + OIDC login reconcile), and any role change revokes existing sessions | Single role authority; no stale-role devices |
```

- [ ] **Step 4: Update PROJECT_STRUCTURE.md**

In `PROJECT_STRUCTURE.md` §1, under `modules/`, replace the `passport/` line with:

```
│   │   │   ├── passport/                  # workers, skills, claims, consents, invitations (Plan 2A)
│   │   │   │   ├── enums.py, models.py, repository.py, schemas.py, dependencies.py
│   │   │   │   ├── skills.py, profile.py, consents.py, invitations.py
│   │   │   │   ├── router.py
│   │   │   │   └── service.py
```

and replace the `integrations/` block's `email/` line with `│   │   │       ├── smtp.py                # SmtpMailer; service.py exposes build_mailer`.

- [ ] **Step 5: Full verification**

Run: `ruff format --check . && ruff check . && mypy && lint-imports && pytest --cov=app --cov-report=term-missing`
Expected: all pass; record the test count and coverage in the commit body.

- [ ] **Step 6: Commit**

```bash
cd ..
git add backend docs PROJECT_STRUCTURE.md
git commit -m "chore: forbid body-addressed workers; record Plan 2A in roadmap and docs"
```

---

## Spec coverage for this plan

| Spec / carry-forward item | Task |
|---|---|
| §7.2 passport: `GET /workers/{id}` shaped by visibility, `PATCH /workers/me`, skills, consents, invitations, `GET /skills` | 5, 6, 7, 8 |
| §7.1 summary / detail / self field sets; 404 below visibility | 6 |
| FR-1.1/1.2/1.5/1.6, FR-2.1 (self-reported only), FR-5.1 standard onboarding, FR-9.2/9.6 worker accounts | 4–8 |
| NFR-4.3 consent with legal basis, audited | 7 |
| NFR-8.1/8.2 localized mail, per-account locale | 2, 8 |
| §8.1 magic links: token issued off the request path | 2 |
| Carry-forward: FKs to `workers`, grant worker validation | 4 |
| Carry-forward: role authority, SCIM `remove`/unknown ops, worker role over SCIM, login-time revocation | 3 |
| Carry-forward: magic-link `verify()` role re-check; mail off request path | 2, 3 |
| Carry-forward: body-addressed worker guard (needed before reactivation routes) | 9 |
| Carry-forward (Plan 6, partial): real mailer selection (`SMTP_URL`) | 1 |

Deferred to Plan 2B: projects, staffing, engagements, reactivation, contracts and webhooks, feedback, PM visibility sources, `AccessRevoked` → `project_staff`. Deferred to Plan 3: standing tier calculation, skill verification from reviews, roster read-model. Data export (FR-1.7) stays post-MVA per spec §10.

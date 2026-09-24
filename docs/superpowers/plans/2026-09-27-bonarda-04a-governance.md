# Bonarda Plan 4A — Disputes, Overrides, Audit Trail and Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give workers a way to contest their record and People Ops the tools to act on it:
- disputes with an SLA, whose upheld outcome stops a record counting toward standing;
- manual standing overrides with a required reason;
- an audit-log API;
- worker and PM notifications;
- the Plan 4 carry-forward fixes in identity, passport and governance.

**Architecture:** Builds on Plans 1–3B (all merged to `main`).

`governance` owns disputes but imports no domain module except `identity`. It cannot check whether a disputed record belongs to the worker, so the composition root (`app/wiring.py`) injects one owner lookup per target type, the same way it injects visibility sources.

The outcome of a dispute travels as an outbox event:
- `standing` handles `DisputeResolved`: it asks `engagements` to exclude the feedback, then recalculates.
- `governance` mails the worker.

Standing overrides live in `standing`, which owns `standing_changes`. An override holds until the rules engine's own verdict for the worker moves.

Plan 4B covers the rest of the roadmap's Plan 4: closing projects, first-shot transition rules, concentration rollups, retention and anonymization.

**Tech Stack:** Python 3.12, FastAPI 0.115 (pinned), Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic, Arq, pytest + Testcontainers + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`. Relevant sections:
- §2.2 #8 (a disputed record counts until resolved; an upheld dispute sets `excluded_from_standing` and triggers recalculation)
- §5.1 and §5.2 (governance owns disputes, audit queries and overrides; boundary rules)
- §6.1 (`disputes`, `policy_configs`, `audit_log`)
- §6.3 (erasure: dispute reasons are personal data; the audit log is append-only)
- §6.4 (`disputes (status, due_at)`)
- §7.2 (governance routes; `POST /standing-overrides`)
- §7.7 (`DisputeResolved`, `notify_worker`, `notify_feedback_due`, daily `dispute_sla_reminder`)
- §8.1 (overrides and revocations are audited with a reason)
- §8.5 (disputes carry `due_at`, seed 30 days)

Roadmap with carry-forward and deviations: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`.

## Global Constraints

- Work on branch `feat/governance`, created from `main` after Plan 3B's merge. Run all commands from `backend/` with the venv at `backend/.venv` activated (`source .venv/Scripts/activate` in Git Bash). Docker must be running (Testcontainers Postgres).
- All routes are under `/api/v1`. Errors are RFC 9457 `application/problem+json` with a stable `code` field.
- A module imports another module only through its `service` or `schemas` submodule.
  - `app/main.py`, `app/worker/` and `app/wiring.py` are the composition root and may import anything.
  - `app.core` imports no module.
  - `governance` imports no domain module except `identity`.
  - `passport` and `engagements` never import `standing` or `governance`.
  - No module imports `roster`.
- Every state change a person makes writes `write_audit(...)` on the request's `AsyncSession`, and every domain event goes through `emit_event(...)` on that same session.
- Audit rows and outbox payloads never carry free text a person wrote about a worker: dispute reasons, resolution notes and feedback text stay in their own tables (spec §6.3). Override reasons are the exception: spec §8.1 requires the reason on the audit row.
- Worker-scoped routes put the worker in the path and declare `require_visibility(...)`. Request bodies never carry `worker_id` (the visibility-guard test enforces both).
- Lock order, recorded in the roadmap:
  - workers: `FOR NO KEY UPDATE`, in id order;
  - skill claims: `FOR UPDATE`, sorted by skill id;
  - roster refreshes: serialized per worker with a transaction-level advisory lock.
  - This plan adds one: a feedback row (`FOR UPDATE`) is locked before its worker.
- Integrity errors are mapped by constraint or index name via `app.core.db.errors.violated_constraint(exc)`. Any other integrity error is re-raised.
- Enum columns use `app.core.db.types.pg_enum`. In migrations:
  - Check-constraint names go through `op.f("ck_<table>_<name>")`.
  - Unique, foreign-key, primary-key and index names are plain strings.
- Datetimes are timezone-aware UTC (`app.core.time.utcnow()`).
- Mail text comes from `app.core.i18n` in the recipient's locale. Every key exists in both `en` and `fr`.
- Notification handlers skip silently when the recipient has no account; they never fail the event.
- Async tests: never call `session.expire_all()` and then `session.get(...)`. Use `await session.refresh(obj)`.
- Before every commit, run this from `backend/` with no path arguments; all of it must pass: `ruff format . && ruff check . && mypy && lint-imports && pytest`.
- Commit messages are multi-line: a subject, a blank line, then a `Co-Authored-By:` trailer naming the model that wrote the commit.

## Review Focus

1. **A worker disputing someone else's record.** Filing a dispute against another worker's feedback, or against an id that does not exist, answers the same 404. No dispute row is written. (Test in Task 3.)
2. **Double submission.** A second open dispute on the same record is refused with 409 and leaves exactly one row. (Test in Task 3.)
3. **The nightly run erasing an override.** After People Ops overrides a tier, the nightly re-evaluation leaves it in place. It moves only once the rules' own verdict changes. (Tests in Task 5.)
4. **An upheld outcome applied twice.** Excluding feedback that is already excluded changes nothing and writes no second audit row. (Test in Task 4.)
5. **Mail to a worker with no account.** An engagement starting for a worker without an account sends nothing and raises nothing, so the event never dead-letters. (Test in Task 6.)

---

## File Structure

```
backend/
  alembic/versions/0012_policy_guards.py        policy invariants: check + update trigger (Task 1)
  alembic/versions/0013_disputes.py             disputes table (Task 3)
  app/
    core/pagination.py                          opaque keyset cursors (Task 2)
    core/config.py                              + dispute_sla_days, dispute_reminder_days (Tasks 3, 7)
    core/i18n.py                                + notification messages (Tasks 6, 7)
    main.py                                     + app.state.dispute_target_owners (Task 3)
    wiring.py                                   + dispute_target_owners(); handlers get the mailer (Tasks 3, 6)
    worker/jobs.py, worker/settings.py          + remind_dispute_sla at 08:00; ctx mailer + settings (Task 7)
    modules/governance/
      enums.py, models.py                       + dispute enums, Dispute; policy check (Tasks 1, 3)
      repository.py                             + AuditLogRepository (Task 2), DisputeRepository (Task 3)
      schemas.py                                + audit, dispute schemas and events (Tasks 2, 3)
      audit.py                                  audit_trail() (Task 2)
      disputes.py                               DisputeService, TargetOwner (Task 3)
      notifications.py, handlers.py             dispute-resolved mail (Task 6)
      reminders.py                              remind_due_disputes() (Task 7)
      router.py, service.py
    modules/standing/
      queries.py                                standing_change_worker_id() (Task 3)
      overrides.py                              override_standing() (Task 5)
      notifications.py                          standing-changed mail (Task 6)
      recalculation.py, repository.py           override holds until the verdict moves (Task 5)
      handlers.py, router.py, schemas.py, explanation.py, service.py
    modules/engagements/
      queries.py, feedback.py, repository.py    feedback_worker_id, engagement_feedback_id, exclude_feedback (Tasks 3, 4)
      notifications.py                          engagement-confirmed and feedback-due mail (Task 6)
      handlers.py, schemas.py, service.py
    modules/identity/
      access_revocation.py                      revoke_access(): one path for SCIM and OIDC (Task 8)
      accounts.py, grants.py, sessions.py, oidc_login.py, scim.py, router.py, schemas.py, service.py
    modules/passport/consents.py, profile.py    audit before-values, worker.renamed, no-op PATCH (Task 9)
  tests/support.py                              + make_dispute()
  tests/…                                       one file per task
docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md, PROJECT_STRUCTURE.md   (Task 9)
```

---

### Task 1: Policy invariants in the database

Closes the roadmap row "Add DB invariants for policies". A live policy (`active` or `retired`) must have `activated_at`. A proposed policy's rules can never be edited, and status only moves draft → active → retired.

**Files:**
- Create: `backend/alembic/versions/0012_policy_guards.py`
- Modify: `backend/app/modules/governance/models.py`
- Test: `backend/tests/integration/test_policy_guards.py`

**Interfaces:**
- Consumes: `PolicyConfig` (governance.models), `_seed_policy_rows()` and `make_user()` (tests.support).
- Produces: check constraint `ck_policy_configs_activated_when_live`; trigger `policy_configs_guard` calling `guard_policy_update()`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_policy_guards.py`:

```python
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.models import PolicyConfig
from app.modules.identity.models import UserAccount
from tests.support import _seed_policy_rows, make_user


def _tiering_rules() -> dict[str, Any]:
    rules: dict[str, Any] = next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering")
    return rules


async def _draft(session: AsyncSession, author: UserAccount) -> PolicyConfig:
    policy = PolicyConfig(
        kind=PolicyKind.TIERING, version=2, rules=_tiering_rules(), created_by_id=author.id
    )
    session.add(policy)
    await session.commit()
    return policy


_SEED_TIERING = (PolicyConfig.kind == PolicyKind.TIERING) & (PolicyConfig.version == 1)


@pytest.mark.parametrize(
    "values", [{"rules": {"window_months": 1}}, {"notes": "edited"}, {"version": 7}]
)
async def test_a_proposed_policy_cannot_be_edited(
    session: AsyncSession, values: dict[str, Any]
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    policy = await _draft(session, ops)

    with pytest.raises(DBAPIError, match="a proposed policy is immutable"):
        await session.execute(
            update(PolicyConfig).where(PolicyConfig.id == policy.id).values(**values)
        )
    await session.rollback()


async def test_a_draft_cannot_be_retired_without_going_live(session: AsyncSession) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    policy = await _draft(session, ops)

    with pytest.raises(DBAPIError, match="cannot move from draft to retired"):
        await session.execute(
            update(PolicyConfig)
            .where(PolicyConfig.id == policy.id)
            .values(status=PolicyStatus.RETIRED)
        )
    await session.rollback()


async def test_a_live_policy_cannot_return_to_draft(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="cannot move from active to draft"):
        await session.execute(
            update(PolicyConfig).where(_SEED_TIERING).values(status=PolicyStatus.DRAFT)
        )
    await session.rollback()


async def test_the_activation_stamp_is_fixed_once_live(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="activation is immutable"):
        await session.execute(
            update(PolicyConfig)
            .where(_SEED_TIERING)
            .values(activated_at=utcnow() - timedelta(days=1))
        )
    await session.rollback()


async def test_a_live_policy_needs_an_activation_time(session: AsyncSession) -> None:
    session.add(
        PolicyConfig(
            kind=PolicyKind.CONCENTRATION, version=1, rules={}, status=PolicyStatus.ACTIVE
        )
    )

    with pytest.raises(IntegrityError, match="ck_policy_configs_activated_when_live"):
        await session.commit()


async def test_deleting_the_author_still_clears_created_by(session: AsyncSession) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    policy = await _draft(session, ops)

    await session.execute(delete(UserAccount).where(UserAccount.id == ops.id))
    await session.commit()

    await session.refresh(policy)
    assert policy.created_by_id is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/integration/test_policy_guards.py -v`
Expected: FAIL. The edits succeed (`DID NOT RAISE`), and the live-policy insert commits.

- [ ] **Step 3: Add the check constraint to the model**

In `backend/app/modules/governance/models.py`, add a line to `PolicyConfig.__table_args__` after `CheckConstraint("version > 0", name="version_positive")`:

```python
        CheckConstraint("status = 'draft' OR activated_at IS NOT NULL", name="activated_when_live"),
```

Update the class docstring so it states what the database now enforces:

```python
    """A versioned rule set People Ops controls (NFR-5.1, NFR-9.2). Once
    proposed, a row changes only through its status lifecycle (draft → active
    → retired); the `policy_configs_guard` trigger (migration 0012) enforces it."""
```

- [ ] **Step 4: Write the migration**

`backend/alembic/versions/0012_policy_guards.py`:

```python
"""governance: policy_configs invariants (live ⇒ activated_at; immutable once proposed)

Revision ID: 0012_policy_guards
Revises: 0011_first_shot
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_policy_guards"
down_revision: str | None = "0011_first_shot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_policy_configs_activated_when_live"),
        "policy_configs",
        "status = 'draft' OR activated_at IS NOT NULL",
    )
    # NFR-5.1: a proposed rule set is the record of what was approved. Only
    # the status lifecycle and a draft's activation stamp may change. An
    # author or activator column may still become NULL (FK ON DELETE SET NULL).
    op.execute(
        """
        CREATE FUNCTION guard_policy_update() RETURNS trigger AS $$
        BEGIN
          IF NEW.kind IS DISTINCT FROM OLD.kind
             OR NEW.version IS DISTINCT FROM OLD.version
             OR NEW.rules IS DISTINCT FROM OLD.rules
             OR NEW.notes IS DISTINCT FROM OLD.notes
             OR (NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
                 AND NEW.created_by_id IS NOT NULL) THEN
            RAISE EXCEPTION 'policy_configs: a proposed policy is immutable';
          END IF;
          IF OLD.status <> 'draft'
             AND (NEW.activated_at IS DISTINCT FROM OLD.activated_at
                  OR (NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id
                      AND NEW.activated_by_id IS NOT NULL)) THEN
            RAISE EXCEPTION 'policy_configs: activation is immutable';
          END IF;
          IF NEW.status IS DISTINCT FROM OLD.status
             AND NOT ((OLD.status = 'draft' AND NEW.status = 'active')
                      OR (OLD.status = 'active' AND NEW.status = 'retired')) THEN
            RAISE EXCEPTION 'policy_configs: status cannot move from % to %',
              OLD.status, NEW.status;
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER policy_configs_guard BEFORE UPDATE ON policy_configs "
        "FOR EACH ROW EXECUTE FUNCTION guard_policy_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS policy_configs_guard ON policy_configs")
    op.execute("DROP FUNCTION IF EXISTS guard_policy_update()")
    op.drop_constraint(
        op.f("ck_policy_configs_activated_when_live"), "policy_configs", type_="check"
    )
```

- [ ] **Step 5: Run the new tests, the policy API tests and the migration tests**

Run: `pytest tests/integration/test_policy_guards.py tests/api/governance tests/integration/test_migrations.py -v`
Expected: PASS. Activation through `PolicyService` still works: it moves a draft to active with its stamp, and the old version to retired, which the trigger allows.

- [ ] **Step 6: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic/versions/0012_policy_guards.py app/modules/governance/models.py tests/integration/test_policy_guards.py
git commit -m "feat(governance): enforce policy invariants in the database

A live policy needs an activation time, and a proposed policy is immutable
apart from its draft -> active -> retired lifecycle.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 2: The audit-log API

`GET /governance/audit-log` (FR-7.3) lets People Ops and admins read the trail for one record, newest first, in keyset pages. The shared cursor helper is reused by the dispute queue in Task 3.

**Files:**
- Create: `backend/app/core/pagination.py`, `backend/app/modules/governance/audit.py`
- Modify: `backend/app/modules/governance/repository.py`, `schemas.py`, `router.py`
- Test: `backend/tests/unit/test_pagination.py`, `backend/tests/api/governance/test_audit_log.py`

**Interfaces:**
- Consumes: `AuditLog` (app.core.audit.models), `Permission.AUDIT_READ` (identity.service), `write_audit`.
- Produces:
  - `app.core.pagination.encode_cursor(values: dict[str, str]) -> str` and `decode_cursor(cursor: str, keys: tuple[str, ...]) -> dict[str, str]`. `decode_cursor` raises `BadRequest(code="invalid_cursor")`.
  - `governance.schemas.AuditEntryRead` and `AuditLogPage(items, next_cursor)`.
  - `governance.repository.AuditLogRepository(session).page(*, target_type, target_id, action, before_id, limit) -> list[AuditLog]`.
  - `governance.audit.audit_trail(session, *, target_type, target_id, action, cursor, limit) -> AuditLogPage`.
  - Route `GET /api/v1/governance/audit-log?target_type=&target_id=&action=&cursor=&limit=` (permission `audit:read`).

- [ ] **Step 1: Write the failing cursor tests**

`backend/tests/unit/test_pagination.py`:

```python
import base64
import json

import pytest

from app.core.errors import BadRequest
from app.core.pagination import decode_cursor, encode_cursor


def test_a_cursor_round_trips() -> None:
    cursor = encode_cursor({"id": "42", "due_at": "2026-10-01T00:00:00+00:00"})

    assert decode_cursor(cursor, ("due_at", "id")) == {
        "id": "42",
        "due_at": "2026-10-01T00:00:00+00:00",
    }


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(json.dumps(["id"]).encode()).decode(),
        encode_cursor({"other": "1"}),
        encode_cursor({"id": "1", "extra": "2"}),
        base64.urlsafe_b64encode(json.dumps({"id": 1}).encode()).decode(),
    ],
)
def test_a_malformed_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(BadRequest) as excinfo:
        decode_cursor(cursor, ("id",))

    assert excinfo.value.code == "invalid_cursor"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit/test_pagination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.pagination'`.

- [ ] **Step 3: Write the cursor helper**

`backend/app/core/pagination.py`:

```python
"""Opaque keyset cursors (spec §7.2). A cursor is base64 JSON of string
values; callers parse and validate each value themselves."""

import base64
import binascii
import json

from app.core.errors import BadRequest


def _invalid() -> BadRequest:
    return BadRequest("Invalid cursor", code="invalid_cursor")


def encode_cursor(values: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str, keys: tuple[str, ...]) -> dict[str, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError) as exc:
        raise _invalid() from exc
    if not isinstance(data, dict) or set(data) != set(keys):
        raise _invalid()
    if not all(isinstance(data[key], str) for key in keys):
        raise _invalid()
    return {key: data[key] for key in keys}
```

- [ ] **Step 4: Run the cursor tests to verify they pass**

Run: `pytest tests/unit/test_pagination.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing API tests**

`backend/tests/api/governance/test_audit_log.py`:

```python
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.pagination import encode_cursor
from tests.support import bearer, make_user

URL = "/api/v1/governance/audit-log"


async def _audit(session: AsyncSession, target_id: UUID, *actions: str) -> None:
    for action in actions:
        await write_audit(
            session, actor=None, action=action, target_type="worker", target_id=target_id
        )
    await session.commit()


async def test_people_ops_read_one_records_trail_newest_first(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    worker_id = uuid4()
    await _audit(session, worker_id, "worker.invited", "consent.granted")
    await _audit(session, uuid4(), "worker.invited")

    response = await client.get(
        URL,
        params={"target_type": "worker", "target_id": str(worker_id)},
        headers=bearer(settings, ops),
    )

    body = response.json()
    assert response.status_code == 200
    assert [e["action"] for e in body["items"]] == ["consent.granted", "worker.invited"]
    assert {e["target_id"] for e in body["items"]} == {str(worker_id)}
    assert body["next_cursor"] is None


async def test_pages_follow_on_without_overlap(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _audit(session, uuid4(), "a.one", "a.two", "a.three")
    headers = bearer(settings, ops)

    first = (await client.get(URL, params={"limit": 2}, headers=headers)).json()
    second = (
        await client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)
    ).json()

    assert [e["action"] for e in first["items"]] == ["a.three", "a.two"]
    assert [e["action"] for e in second["items"]] == ["a.one"]
    assert second["next_cursor"] is None


async def test_filters_by_action(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _audit(session, uuid4(), "consent.granted", "worker.invited", "consent.granted")

    response = await client.get(
        URL, params={"action": "consent.granted"}, headers=bearer(settings, ops)
    )

    assert [e["action"] for e in response.json()["items"]] == ["consent.granted"] * 2


@pytest.mark.parametrize(
    ("role", "status"), [(UserRole.ADMIN, 200), (UserRole.PM, 403), (UserRole.FINANCE, 403)]
)
async def test_only_audit_readers_see_the_trail(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole, status: int
) -> None:
    user = await make_user(session, role=role)

    response = await client.get(URL, headers=bearer(settings, user))

    assert response.status_code == status


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        encode_cursor({"x": "1"}),
        encode_cursor({"id": "abc"}),
        encode_cursor({"id": "0"}),
        encode_cursor({"id": "9" * 30}),
    ],
)
async def test_a_tampered_cursor_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, cursor: str
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(URL, params={"cursor": cursor}, headers=bearer(settings, ops))

    assert (response.status_code, response.json()["code"]) == (400, "invalid_cursor")


async def test_target_id_needs_a_target_type(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(
        URL, params={"target_id": str(uuid4())}, headers=bearer(settings, ops)
    )

    assert (response.status_code, response.json()["code"]) == (400, "target_type_required")
```

- [ ] **Step 6: Run them to verify they fail**

Run: `pytest tests/api/governance/test_audit_log.py -v`
Expected: FAIL with 404 (the route does not exist yet).

- [ ] **Step 7: Add the schemas**

Append to `backend/app/modules/governance/schemas.py`:

```python
class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_role: str | None
    action: str
    target_type: str
    target_id: UUID
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    correlation_id: str | None


class AuditLogPage(BaseModel):
    items: list[AuditEntryRead]
    next_cursor: str | None
```

- [ ] **Step 8: Add the repository**

Append to `backend/app/modules/governance/repository.py`, and add `from app.core.audit.models import AuditLog` to its imports:

```python
class AuditLogRepository:
    """Reads app.core's audit_log (FR-7.3). The table has no owner module;
    governance is the only reader."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def page(
        self,
        *,
        target_type: str | None,
        target_id: UUID | None,
        action: str | None,
        before_id: int | None,
        limit: int,
    ) -> list[AuditLog]:
        stmt = select(AuditLog)
        if target_type is not None:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if before_id is not None:
            stmt = stmt.where(AuditLog.id < before_id)
        stmt = stmt.order_by(AuditLog.id.desc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())
```

- [ ] **Step 9: Write the service**

`backend/app/modules/governance/audit.py`:

```python
"""The audit-trail reader (FR-7.3): newest first, keyset-paged on the row id."""

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.governance.repository import AuditLogRepository
from app.modules.governance.schemas import AuditEntryRead, AuditLogPage

# A positive bigint that fits in 18 digits.
_ROW_ID = re.compile(r"[1-9][0-9]{0,17}")


def _before_id(cursor: str) -> int:
    raw = decode_cursor(cursor, ("id",))["id"]
    if not _ROW_ID.fullmatch(raw):
        raise BadRequest("Invalid cursor", code="invalid_cursor")
    return int(raw)


async def audit_trail(
    session: AsyncSession,
    *,
    target_type: str | None,
    target_id: UUID | None,
    action: str | None,
    cursor: str | None,
    limit: int,
) -> AuditLogPage:
    if target_id is not None and target_type is None:
        raise BadRequest("target_id needs target_type", code="target_type_required")
    rows = await AuditLogRepository(session).page(
        target_type=target_type,
        target_id=target_id,
        action=action,
        before_id=_before_id(cursor) if cursor is not None else None,
        limit=limit + 1,
    )
    page = rows[:limit]
    return AuditLogPage(
        items=[AuditEntryRead.model_validate(row) for row in page],
        next_cursor=encode_cursor({"id": str(page[-1].id)}) if len(rows) > limit else None,
    )
```

- [ ] **Step 10: Add the route**

In `backend/app/modules/governance/router.py`, change the imports to:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.governance.audit import audit_trail
from app.modules.governance.enums import PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.schemas import AuditLogPage, PolicyCreate, PolicyRead
from app.modules.identity.service import Permission, require_permission
```

Then add, after `PolicyActivator`:

```python
AuditReader = Annotated[Actor, Depends(require_permission(Permission.AUDIT_READ))]
```

and at the end of the file:

```python
@router.get("/governance/audit-log")
async def read_audit_log(
    actor: AuditReader,
    session: SessionDep,
    target_type: Annotated[str | None, Query(max_length=40)] = None,
    target_id: UUID | None = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AuditLogPage:
    return await audit_trail(
        session,
        target_type=target_type,
        target_id=target_id,
        action=action,
        cursor=cursor,
        limit=limit,
    )
```

- [ ] **Step 11: Run the tests to verify they pass**

Run: `pytest tests/unit/test_pagination.py tests/api/governance/test_audit_log.py -v`
Expected: PASS.

- [ ] **Step 12: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app/core/pagination.py app/modules/governance tests/unit/test_pagination.py tests/api/governance/test_audit_log.py
git commit -m "feat(governance): audit-log API with keyset paging

GET /governance/audit-log reads one record's trail newest first for People
Ops and admins (FR-7.3). Adds a shared opaque-cursor helper.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 3: Disputes — file, list and resolve

A worker files a dispute on their own feedback, standing change or engagement (FR-1.4). People Ops work the queue in SLA order and resolve each dispute once. Workers see only their own disputes.

`governance` cannot import the modules that own those records. `app/wiring.py` therefore supplies one owner lookup per target type, and `create_app` stores them on `app.state`. So that workers can name what they dispute, `FeedbackRead` and `StandingChangeRead` gain an `id`.

**Files:**
- Create: `backend/alembic/versions/0013_disputes.py`, `backend/app/modules/governance/disputes.py`, `backend/app/modules/standing/queries.py`
- Modify: `backend/app/modules/governance/enums.py`, `models.py`, `repository.py`, `schemas.py`, `router.py`, `service.py`; `backend/app/modules/engagements/queries.py`, `schemas.py`, `service.py`; `backend/app/modules/standing/schemas.py`, `explanation.py`, `service.py`; `backend/app/core/config.py`; `backend/app/wiring.py`; `backend/app/main.py`; `backend/tests/support.py`
- Test: `backend/tests/api/governance/test_disputes.py`, `backend/tests/unit/governance/test_dispute_targets.py`

**Interfaces:**
- Consumes: `encode_cursor` / `decode_cursor` (Task 2); `engagements.service.engagement_worker_id(session, engagement_id)`; `identity.service.has_permission`, `Permission`.
- Produces:
  - Enums in `governance.enums`:
    - `DisputeTargetType` (`feedback`, `standing_change`, `engagement`)
    - `DisputeStatus` (`open`, `resolved`)
    - `DisputeResolution` (`upheld`, `rejected`)
  - Model `governance.models.Dispute`, with unique index `uq_disputes_open_target` on `(target_type, target_id) WHERE status = 'open'`.
  - Schemas: `DisputeCreate(target_type, target_id, reason)`, `DisputeResolve(resolution, resolution_notes)`, `DisputeRead`, `DisputePage(items, next_cursor)`.
  - Events:
    - `DisputeFiled(aggregate_id=dispute, worker_id, target_type, target_id)`, event type `governance.dispute_filed`.
    - `DisputeResolved(aggregate_id=dispute, worker_id, target_type, target_id, resolution)`, event type `governance.dispute_resolved`.
  - `governance.disputes`:
    - `TargetOwner = Callable[[AsyncSession, UUID], Awaitable[UUID | None]]`
    - `DisputeTargetOwners = Mapping[DisputeTargetType, TargetOwner]`
    - `DisputeService(session)` with `file(actor, data, *, owners, sla_days)`, `list_for(actor, *, status, cursor, limit)` and `resolve(actor, dispute_id, data)`.
  - `governance.repository.DisputeRepository(session)`: `add`, `get`, `get_for_update`, `page(*, worker_id, status, after, limit)`, `open_due_before(cutoff)`.
  - `governance.service` exports `DisputeResolution`, `DisputeStatus`, `DisputeTargetType`, `DisputeTargetOwners`, `TargetOwner`.
  - `engagements.queries.feedback_worker_id(session, feedback_id) -> UUID | None`, exported from `engagements.service`.
  - `standing.queries.standing_change_worker_id(session, change_id) -> UUID | None`, exported from `standing.service`.
  - `FeedbackRead.id` and `StandingChangeRead.id`.
  - `Settings.dispute_sla_days = 30`.
  - `app.wiring.dispute_target_owners() -> dict[DisputeTargetType, TargetOwner]`; `app.state.dispute_target_owners`.
  - Routes, all under `/api/v1`:
    - `POST /disputes` (permission `dispute:file`, worker accounts only), 201.
    - `GET /disputes?status=&cursor=&limit=`. People Ops see every dispute; a worker sees their own; anyone else gets 403.
    - `PATCH /disputes/{dispute_id}` (permission `dispute:resolve`).
  - Test helper `make_dispute(session, *, worker_id, due_at, target_type=ENGAGEMENT, target_id=None, resolved=False) -> Dispute`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/governance/test_dispute_targets.py`:

```python
from app.modules.governance.enums import DisputeTargetType
from app.wiring import dispute_target_owners


def test_every_target_type_has_an_owner_lookup() -> None:
    assert set(dispute_target_owners()) == set(DisputeTargetType)
```

`backend/tests/api/governance/test_disputes.py`:

```python
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.pagination import encode_cursor
from app.core.time import utcnow
from app.modules.governance.models import Dispute
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import StandingTier
from app.modules.standing.models import StandingChange
from tests.support import (
    bearer,
    make_dispute,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

URL = "/api/v1/disputes"
REASON = "The feedback describes a different project."
NOTES = "Checked with the PM: the feedback was meant for another worker."


async def _reviewed_engagement(session: AsyncSession) -> tuple[UserAccount, UUID, UUID]:
    """A worker's account, one of their completed engagements, and its feedback."""
    pm = await make_user(session, role=UserRole.PM)
    worker, account = await make_worker(session)
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    feedback = await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    return account, engagement.id, feedback.id


def _body(target_type: str, target_id: UUID | str) -> dict[str, str]:
    return {"target_type": target_type, "target_id": str(target_id), "reason": REASON}


async def test_worker_disputes_feedback_from_their_passport(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, _ = await _reviewed_engagement(session)
    headers = bearer(settings, account)
    history = (
        await client.get(f"/api/v1/workers/{account.worker_id}/engagements", headers=headers)
    ).json()
    feedback_id = history[0]["feedback"]["id"]

    response = await client.post(URL, json=_body("feedback", feedback_id), headers=headers)

    body = response.json()
    assert response.status_code == 201
    assert (body["status"], body["worker_id"], body["target_id"]) == (
        "open",
        str(account.worker_id),
        feedback_id,
    )
    remaining = datetime.fromisoformat(body["due_at"]) - utcnow()
    assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "dispute.filed"))
    ).one()
    assert REASON not in json.dumps([audit.before, audit.after])
    event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.dispute_filed")
        )
    ).one()
    assert REASON not in json.dumps(event.payload)


async def test_worker_disputes_an_engagement_and_a_standing_change(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, engagement_id, _ = await _reviewed_engagement(session)
    assert account.worker_id is not None
    change = StandingChange(
        worker_id=account.worker_id,
        previous_tier=StandingTier.UNRATED,
        new_tier=StandingTier.TIER_1,
        contributing_factors={},
    )
    session.add(change)
    await session.commit()
    headers = bearer(settings, account)

    standing = (await client.get("/api/v1/workers/me/standing", headers=headers)).json()
    for target_type, target_id in (
        ("engagement", engagement_id),
        ("standing_change", standing["history"][0]["id"]),
    ):
        response = await client.post(URL, json=_body(target_type, target_id), headers=headers)
        assert response.status_code == 201, response.json()

    assert standing["history"][0]["id"] == str(change.id)


async def test_a_worker_cannot_dispute_someone_elses_record(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, _, feedback_id = await _reviewed_engagement(session)
    _, stranger = await make_worker(session, full_name="Ama Owusu")

    for target_id in (feedback_id, uuid4()):
        response = await client.post(
            URL, json=_body("feedback", target_id), headers=bearer(settings, stranger)
        )
        assert (response.status_code, response.json()["code"]) == (
            404,
            "dispute_target_not_found",
        )
    assert (await session.scalars(select(Dispute))).all() == []


async def test_a_record_has_at_most_one_open_dispute(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, feedback_id = await _reviewed_engagement(session)
    headers = bearer(settings, account)

    first = await client.post(URL, json=_body("feedback", feedback_id), headers=headers)
    second = await client.post(URL, json=_body("feedback", feedback_id), headers=headers)

    assert first.status_code == 201
    assert (second.status_code, second.json()["code"]) == (409, "dispute_already_open")
    assert len((await session.scalars(select(Dispute))).all()) == 1


@pytest.mark.parametrize("role", [UserRole.PM, UserRole.PEOPLE_OPS])
async def test_only_workers_file_disputes(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    _, _, feedback_id = await _reviewed_engagement(session)
    staff = await make_user(session, role=role)

    response = await client.post(
        URL, json=_body("feedback", feedback_id), headers=bearer(settings, staff)
    )

    assert (response.status_code, response.json()["code"]) == (403, "permission_denied")


async def test_people_ops_see_the_queue_and_workers_see_their_own(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account_a, _, feedback_a = await _reviewed_engagement(session)
    account_b, _, feedback_b = await _reviewed_engagement(session)
    for account, feedback_id in ((account_a, feedback_a), (account_b, feedback_b)):
        filed = await client.post(
            URL, json=_body("feedback", feedback_id), headers=bearer(settings, account)
        )
        assert filed.status_code == 201
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)

    queue = (await client.get(URL, params={"status": "open"}, headers=bearer(settings, ops))).json()
    own = (await client.get(URL, headers=bearer(settings, account_a))).json()
    pm_view = await client.get(URL, headers=bearer(settings, pm))

    assert [d["worker_id"] for d in queue["items"]] == [
        str(account_a.worker_id),
        str(account_b.worker_id),
    ]
    assert [d["worker_id"] for d in own["items"]] == [str(account_a.worker_id)]
    assert (pm_view.status_code, pm_view.json()["code"]) == (403, "permission_denied")


async def test_the_queue_pages_in_due_order(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    now = utcnow()
    disputes = [
        await make_dispute(session, worker_id=worker.id, due_at=now + timedelta(days=days))
        for days in (3, 1, 2)
    ]
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    headers = bearer(settings, ops)

    first = (await client.get(URL, params={"limit": 2}, headers=headers)).json()
    second = (
        await client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)
    ).json()
    tampered = await client.get(
        URL, params={"cursor": encode_cursor({"due_at": "yesterday", "id": "x"})}, headers=headers
    )

    ids = [d["id"] for d in first["items"] + second["items"]]
    assert ids == [str(disputes[1].id), str(disputes[2].id), str(disputes[0].id)]
    assert second["next_cursor"] is None
    assert (tampered.status_code, tampered.json()["code"]) == (400, "invalid_cursor")


async def test_people_ops_resolve_a_dispute_once(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, feedback_id = await _reviewed_engagement(session)
    filed = (
        await client.post(
            URL, json=_body("feedback", feedback_id), headers=bearer(settings, account)
        )
    ).json()
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    decision = {"resolution": "upheld", "resolution_notes": NOTES}

    response = await client.patch(
        f"{URL}/{filed['id']}", json=decision, headers=bearer(settings, ops)
    )
    again = await client.patch(f"{URL}/{filed['id']}", json=decision, headers=bearer(settings, ops))

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["resolution"], body["resolver_id"]) == (
        "resolved",
        "upheld",
        str(ops.id),
    )
    assert body["resolution_notes"] == NOTES
    assert (again.status_code, again.json()["code"]) == (409, "dispute_already_resolved")
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "dispute.resolved"))
    ).one()
    assert (audit.before, audit.after) == (
        {"status": "open"},
        {"status": "resolved", "resolution": "upheld"},
    )
    event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.dispute_resolved")
        )
    ).one()
    assert event.payload["resolution"] == "upheld"
    assert NOTES not in json.dumps(event.payload)


async def test_workers_cannot_resolve_and_unknown_disputes_are_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, feedback_id = await _reviewed_engagement(session)
    filed = (
        await client.post(
            URL, json=_body("feedback", feedback_id), headers=bearer(settings, account)
        )
    ).json()
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    decision = {"resolution": "rejected", "resolution_notes": NOTES}

    by_worker = await client.patch(
        f"{URL}/{filed['id']}", json=decision, headers=bearer(settings, account)
    )
    unknown = await client.patch(f"{URL}/{uuid4()}", json=decision, headers=bearer(settings, ops))

    assert (by_worker.status_code, by_worker.json()["code"]) == (403, "permission_denied")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "dispute_not_found")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit/governance/test_dispute_targets.py tests/api/governance/test_disputes.py -v`
Expected: FAIL with `ImportError` (no `DisputeTargetType`, `dispute_target_owners`, `make_dispute` or `Dispute`).

- [ ] **Step 3: Add the enums**

Append to `backend/app/modules/governance/enums.py`:

```python
class DisputeTargetType(enum.StrEnum):
    FEEDBACK = "feedback"
    STANDING_CHANGE = "standing_change"
    ENGAGEMENT = "engagement"


class DisputeStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class DisputeResolution(enum.StrEnum):
    UPHELD = "upheld"
    REJECTED = "rejected"
```

- [ ] **Step 4: Add the model**

In `backend/app/modules/governance/models.py`, change the enum import to:

```python
from app.modules.governance.enums import (
    DisputeResolution,
    DisputeStatus,
    DisputeTargetType,
    PolicyKind,
    PolicyStatus,
)
```

and append:

```python
class Dispute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A worker contesting a record on their passport (FR-1.4). `reason` and
    `resolution_notes` are personal data: audit rows and outbox payloads never
    copy them (spec §6.3)."""

    __tablename__ = "disputes"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    target_type: Mapped[DisputeTargetType] = mapped_column(
        pg_enum(DisputeTargetType), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(
        pg_enum(DisputeStatus),
        default=DisputeStatus.OPEN,
        server_default=DisputeStatus.OPEN.value,
        nullable=False,
    )
    resolution: Mapped[DisputeResolution | None] = mapped_column(pg_enum(DisputeResolution))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolver_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_disputes_status_due", "status", "due_at"),
        Index("ix_disputes_worker", "worker_id"),
        Index(
            "uq_disputes_open_target",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name="resolved_consistent",
        ),
    )
```

- [ ] **Step 5: Write the migration**

`backend/alembic/versions/0013_disputes.py`:

```python
"""governance: disputes

Revision ID: 0013_disputes
Revises: 0012_policy_guards
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_disputes"
down_revision: str | None = "0012_policy_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "disputes",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column(
            "target_type",
            sa.Enum("feedback", "standing_change", "engagement", name="disputetargettype"),
            nullable=False,
        ),
        sa.Column("target_id", _UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "resolved", name="disputestatus"),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "resolution", sa.Enum("upheld", "rejected", name="disputeresolution"), nullable=True
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolver_id", _UUID, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_disputes"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_disputes_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resolver_id"],
            ["user_accounts.id"],
            name="fk_disputes_resolver_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name=op.f("ck_disputes_resolved_consistent"),
        ),
    )
    op.create_index("ix_disputes_status_due", "disputes", ["status", "due_at"])
    op.create_index("ix_disputes_worker", "disputes", ["worker_id"])
    op.create_index(
        "uq_disputes_open_target",
        "disputes",
        ["target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_disputes_open_target", table_name="disputes")
    op.drop_index("ix_disputes_worker", table_name="disputes")
    op.drop_index("ix_disputes_status_due", table_name="disputes")
    op.drop_table("disputes")
    op.execute("DROP TYPE disputeresolution")
    op.execute("DROP TYPE disputestatus")
    op.execute("DROP TYPE disputetargettype")
```

- [ ] **Step 6: Add the schemas and events**

In `backend/app/modules/governance/schemas.py`, change the enum import to:

```python
from app.modules.governance.enums import (
    DisputeResolution,
    DisputeStatus,
    DisputeTargetType,
    PolicyKind,
    PolicyStatus,
)
```

and append:

```python
class DisputeCreate(BaseModel):
    """The worker is the caller; a body never names a worker (spec §7.1)."""

    model_config = ConfigDict(extra="forbid")

    target_type: DisputeTargetType
    target_id: UUID
    reason: str = Field(min_length=10, max_length=2000)


class DisputeResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: DisputeResolution
    resolution_notes: str = Field(min_length=10, max_length=2000)


class DisputeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    worker_id: UUID
    target_type: DisputeTargetType
    target_id: UUID
    reason: str
    status: DisputeStatus
    resolution: DisputeResolution | None
    resolution_notes: str | None
    resolver_id: UUID | None
    resolved_at: datetime | None
    due_at: datetime
    created_at: datetime


class DisputePage(BaseModel):
    items: list[DisputeRead]
    next_cursor: str | None


class DisputeFiled(DomainEvent):
    """aggregate_id is the dispute. No reason text: it is personal data."""

    event_type: ClassVar[str] = "governance.dispute_filed"
    worker_id: UUID
    target_type: DisputeTargetType
    target_id: UUID


class DisputeResolved(DomainEvent):
    """aggregate_id is the dispute. No notes text: handlers read the row."""

    event_type: ClassVar[str] = "governance.dispute_resolved"
    worker_id: UUID
    target_type: DisputeTargetType
    target_id: UUID
    resolution: DisputeResolution
```

- [ ] **Step 7: Add the repository**

Append to `backend/app/modules/governance/repository.py`. Update its imports:
- change the SQLAlchemy import to `from sqlalchemy import and_, func, or_, select`;
- add `from datetime import datetime`;
- add `DisputeStatus` to the existing `governance.enums` import;
- add `Dispute` to the existing `governance.models` import.

```python
class DisputeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, dispute: Dispute) -> Dispute:
        self.session.add(dispute)
        return dispute

    async def get(self, dispute_id: UUID) -> Dispute | None:
        return await self.session.get(Dispute, dispute_id)

    async def get_for_update(self, dispute_id: UUID) -> Dispute | None:
        return await self.session.scalar(
            select(Dispute).where(Dispute.id == dispute_id).with_for_update()
        )

    async def page(
        self,
        *,
        worker_id: UUID | None,
        status: DisputeStatus | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Dispute]:
        """Oldest due first: the order People Ops work the queue in."""
        stmt = select(Dispute)
        if worker_id is not None:
            stmt = stmt.where(Dispute.worker_id == worker_id)
        if status is not None:
            stmt = stmt.where(Dispute.status == status)
        if after is not None:
            due_at, dispute_id = after
            stmt = stmt.where(
                or_(
                    Dispute.due_at > due_at,
                    and_(Dispute.due_at == due_at, Dispute.id > dispute_id),
                )
            )
        stmt = stmt.order_by(Dispute.due_at, Dispute.id).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def open_due_before(self, cutoff: datetime) -> list[Dispute]:
        stmt = (
            select(Dispute)
            .where(Dispute.status == DisputeStatus.OPEN, Dispute.due_at <= cutoff)
            .order_by(Dispute.due_at, Dispute.id)
        )
        return list((await self.session.scalars(stmt)).all())
```

- [ ] **Step 8: Write the service**

`backend/app/modules/governance/disputes.py`:

```python
"""Disputes (FR-1.4, spec §2.2 #8). governance imports no domain module, so
whether a record belongs to the worker is answered by owner lookups that the
composition root injects (app.wiring.dispute_target_owners)."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.outbox.writer import emit_event
from app.core.pagination import decode_cursor, encode_cursor
from app.core.time import utcnow
from app.modules.governance.enums import DisputeStatus, DisputeTargetType
from app.modules.governance.models import Dispute
from app.modules.governance.repository import DisputeRepository
from app.modules.governance.schemas import (
    DisputeCreate,
    DisputeFiled,
    DisputePage,
    DisputeRead,
    DisputeResolve,
    DisputeResolved,
)
from app.modules.identity.service import Permission, has_permission

# The worker a record belongs to, or None when there is no such record.
TargetOwner = Callable[[AsyncSession, UUID], Awaitable[UUID | None]]
DisputeTargetOwners = Mapping[DisputeTargetType, TargetOwner]


def _invalid_cursor() -> BadRequest:
    return BadRequest("Invalid cursor", code="invalid_cursor")


def _after(cursor: str) -> tuple[datetime, UUID]:
    values = decode_cursor(cursor, ("due_at", "id"))
    try:
        due_at = datetime.fromisoformat(values["due_at"])
        dispute_id = UUID(values["id"])
    except ValueError as exc:
        raise _invalid_cursor() from exc
    if due_at.tzinfo is None:
        raise _invalid_cursor()
    return due_at, dispute_id


class DisputeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.disputes = DisputeRepository(session)

    async def file(
        self, actor: Actor, data: DisputeCreate, *, owners: DisputeTargetOwners, sla_days: int
    ) -> Dispute:
        if actor.worker_id is None:
            raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
        # Someone else's record and a missing one answer alike, so the
        # endpoint cannot be used to probe which records exist.
        if await owners[data.target_type](self.session, data.target_id) != actor.worker_id:
            raise NotFound("No such record on your passport", code="dispute_target_not_found")
        try:
            async with self.session.begin_nested():
                dispute = self.disputes.add(
                    Dispute(
                        worker_id=actor.worker_id,
                        target_type=data.target_type,
                        target_id=data.target_id,
                        reason=data.reason,
                        due_at=utcnow() + timedelta(days=sla_days),
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_disputes_open_target":
                raise
            raise Conflict(
                "This record already has an open dispute", code="dispute_already_open"
            ) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="dispute.filed",
            target_type="dispute",
            target_id=dispute.id,
            after={
                "target_type": dispute.target_type.value,
                "target_id": str(dispute.target_id),
                "due_at": dispute.due_at.isoformat(),
            },
        )
        await emit_event(
            self.session,
            DisputeFiled(
                aggregate_id=dispute.id,
                worker_id=dispute.worker_id,
                target_type=dispute.target_type,
                target_id=dispute.target_id,
            ),
        )
        return dispute

    async def list_for(
        self, actor: Actor, *, status: DisputeStatus | None, cursor: str | None, limit: int
    ) -> DisputePage:
        """People Ops see the whole queue; a worker sees their own disputes."""
        if has_permission(actor.role, Permission.DISPUTE_RESOLVE):
            worker_id = None
        elif actor.worker_id is not None:
            worker_id = actor.worker_id
        else:
            raise Forbidden(
                "Only People Ops and workers can list disputes", code="permission_denied"
            )
        rows = await self.disputes.page(
            worker_id=worker_id,
            status=status,
            after=_after(cursor) if cursor is not None else None,
            limit=limit + 1,
        )
        page = rows[:limit]
        next_cursor = (
            encode_cursor({"due_at": page[-1].due_at.isoformat(), "id": str(page[-1].id)})
            if len(rows) > limit
            else None
        )
        return DisputePage(
            items=[DisputeRead.model_validate(d) for d in page], next_cursor=next_cursor
        )

    async def resolve(self, actor: Actor, dispute_id: UUID, data: DisputeResolve) -> Dispute:
        dispute = await self.disputes.get_for_update(dispute_id)
        if dispute is None:
            raise NotFound("Dispute not found", code="dispute_not_found")
        if dispute.status is DisputeStatus.RESOLVED:
            raise Conflict("This dispute is already resolved", code="dispute_already_resolved")
        dispute.status = DisputeStatus.RESOLVED
        dispute.resolution = data.resolution
        dispute.resolution_notes = data.resolution_notes
        dispute.resolver_id = actor.user_id
        dispute.resolved_at = utcnow()
        await write_audit(
            self.session,
            actor=actor,
            action="dispute.resolved",
            target_type="dispute",
            target_id=dispute.id,
            before={"status": DisputeStatus.OPEN.value},
            after={"status": DisputeStatus.RESOLVED.value, "resolution": data.resolution.value},
        )
        await emit_event(
            self.session,
            DisputeResolved(
                aggregate_id=dispute.id,
                worker_id=dispute.worker_id,
                target_type=dispute.target_type,
                target_id=dispute.target_id,
                resolution=data.resolution,
            ),
        )
        return dispute
```

- [ ] **Step 9: Add the routes**

In `backend/app/modules/governance/router.py`, replace the imports with:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.modules.governance.audit import audit_trail
from app.modules.governance.disputes import DisputeService, DisputeTargetOwners
from app.modules.governance.enums import DisputeStatus, PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.schemas import (
    AuditLogPage,
    DisputeCreate,
    DisputePage,
    DisputeRead,
    DisputeResolve,
    PolicyCreate,
    PolicyRead,
)
from app.modules.identity.service import CurrentActor, Permission, require_permission
```

Add these after `AuditReader`:

```python
DisputeFiler = Annotated[Actor, Depends(require_permission(Permission.DISPUTE_FILE))]
DisputeResolver = Annotated[Actor, Depends(require_permission(Permission.DISPUTE_RESOLVE))]


def get_dispute_target_owners(request: Request) -> DisputeTargetOwners:
    return request.app.state.dispute_target_owners


TargetOwnersDep = Annotated[DisputeTargetOwners, Depends(get_dispute_target_owners)]
```

and append:

```python
@router.post("/disputes", status_code=201)
async def file_dispute(
    body: DisputeCreate,
    actor: DisputeFiler,
    session: SessionDep,
    settings: SettingsDep,
    owners: TargetOwnersDep,
) -> DisputeRead:
    dispute = await DisputeService(session).file(
        actor, body, owners=owners, sla_days=settings.dispute_sla_days
    )
    return DisputeRead.model_validate(dispute)


@router.get("/disputes")
async def list_disputes(
    actor: CurrentActor,
    session: SessionDep,
    status: DisputeStatus | None = None,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DisputePage:
    return await DisputeService(session).list_for(
        actor, status=status, cursor=cursor, limit=limit
    )


@router.patch("/disputes/{dispute_id}")
async def resolve_dispute(
    dispute_id: UUID, body: DisputeResolve, actor: DisputeResolver, session: SessionDep
) -> DisputeRead:
    return DisputeRead.model_validate(await DisputeService(session).resolve(actor, dispute_id, body))
```

- [ ] **Step 10: Export the public names**

Replace `backend/app/modules/governance/service.py` with:

```python
"""Public interface of the governance module."""

from app.modules.governance.disputes import DisputeTargetOwners, TargetOwner
from app.modules.governance.enums import (
    DisputeResolution,
    DisputeStatus,
    DisputeTargetType,
    PolicyKind,
    PolicyStatus,
)
from app.modules.governance.policies import active_matching, active_tiering, policy_versions

__all__ = [
    "DisputeResolution",
    "DisputeStatus",
    "DisputeTargetOwners",
    "DisputeTargetType",
    "PolicyKind",
    "PolicyStatus",
    "TargetOwner",
    "active_matching",
    "active_tiering",
    "policy_versions",
]
```

- [ ] **Step 11: Add the owner lookups and the record ids**

Append to `backend/app/modules/engagements/queries.py`:

```python
async def feedback_worker_id(session: AsyncSession, feedback_id: UUID) -> UUID | None:
    return await session.scalar(
        select(Engagement.worker_id)
        .join(Feedback, Feedback.engagement_id == Engagement.id)
        .where(Feedback.id == feedback_id)
    )
```

In `backend/app/modules/engagements/service.py`, add `feedback_worker_id` to the `queries` import and to `__all__`.

In `backend/app/modules/engagements/schemas.py`, make `id: UUID` the first field of `FeedbackRead`.

`backend/app/modules/standing/queries.py`:

```python
"""Read functions other modules use through standing.service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.standing.models import StandingChange


async def standing_change_worker_id(session: AsyncSession, change_id: UUID) -> UUID | None:
    return await session.scalar(
        select(StandingChange.worker_id).where(StandingChange.id == change_id)
    )
```

Replace `backend/app/modules/standing/service.py` with:

```python
"""Public interface of the standing module."""

from app.modules.standing.queries import standing_change_worker_id
from app.modules.standing.recalculation import recalculate_all_standing
from app.modules.standing.schemas import SkillVerified, StandingChanged

__all__ = [
    "SkillVerified",
    "StandingChanged",
    "recalculate_all_standing",
    "standing_change_worker_id",
]
```

In `backend/app/modules/standing/schemas.py`, make `id: UUID` the first field of `StandingChangeRead`. In `backend/app/modules/standing/explanation.py`, pass `id=c.id,` as the first argument of `StandingChangeRead(...)`.

- [ ] **Step 12: Wire the owners, the setting and the test helper**

In `backend/app/core/config.py`, after `payroll_signal_grace_minutes`:

```python
    # Spec §8.5: a dispute is due this many days after it is filed (seed: 30).
    dispute_sla_days: int = 30
```

In `backend/app/wiring.py`, replace the single-name `engagements.service` import and add two more:

```python
from app.modules.engagements.service import (
    engagement_worker_id,
    feedback_worker_id,
    project_relationship,
)
from app.modules.governance.service import DisputeTargetType, TargetOwner
from app.modules.standing.service import standing_change_worker_id
```

Then append:

```python
def dispute_target_owners() -> dict[DisputeTargetType, TargetOwner]:
    """Who owns each kind of disputable record. governance imports no domain
    module, so the composition root supplies these lookups."""
    return {
        DisputeTargetType.FEEDBACK: feedback_worker_id,
        DisputeTargetType.STANDING_CHANGE: standing_change_worker_id,
        DisputeTargetType.ENGAGEMENT: engagement_worker_id,
    }
```

In `backend/app/main.py`:
- change `from app.wiring import visibility_sources` to `from app.wiring import dispute_target_owners, visibility_sources`;
- after `app.state.visibility_policy = …`, add:

```python
    app.state.dispute_target_owners = dispute_target_owners()
```

In `backend/tests/support.py`:
- add `timedelta` to the `datetime` import;
- add `from app.modules.governance.enums import DisputeResolution, DisputeStatus, DisputeTargetType`;
- add `Dispute` to the existing `app.modules.governance.models` import.

Then append:

```python
async def make_dispute(
    session: AsyncSession,
    *,
    worker_id: UUID,
    due_at: datetime,
    target_type: DisputeTargetType = DisputeTargetType.ENGAGEMENT,
    target_id: UUID | None = None,
    resolved: bool = False,
) -> Dispute:
    dispute = Dispute(
        worker_id=worker_id,
        target_type=target_type,
        target_id=target_id or uuid4(),
        reason="Seeded dispute reason",
        due_at=due_at,
    )
    if resolved:
        dispute.status = DisputeStatus.RESOLVED
        dispute.resolution = DisputeResolution.REJECTED
        dispute.resolution_notes = "Seeded resolution notes"
        dispute.resolved_at = utcnow() - timedelta(days=1)
    session.add(dispute)
    await session.commit()
    return dispute
```

- [ ] **Step 13: Run the tests to verify they pass**

Run: `pytest tests/unit/governance tests/api/governance tests/api/standing tests/api/engagements tests/integration/test_migrations.py tests/api/test_visibility_guard.py -v`
Expected: PASS. The visibility-guard test still passes, because no dispute route takes a `worker_id`.

- [ ] **Step 14: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic/versions/0013_disputes.py app tests
git commit -m "feat(governance): disputes with an SLA

Workers dispute their own feedback, standing changes and engagements; People
Ops work the queue in due order and resolve each dispute once. Record
ownership comes from lookups the composition root injects, so governance
still imports no domain module.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 4: An upheld dispute stops the record counting

Spec §2.2 #8 and §7.7: when People Ops uphold a dispute on feedback, that feedback gets `excluded_from_standing` and the worker is recalculated. For an upheld engagement dispute, the engagement's feedback is excluded, if it has any.

An upheld standing-change dispute changes no data by itself. The rules engine is deterministic, so People Ops correct the tier with an override (Task 5).

**Files:**
- Modify: `backend/app/modules/engagements/repository.py`, `queries.py`, `feedback.py`, `service.py`; `backend/app/modules/standing/handlers.py`
- Test: `backend/tests/api/standing/test_dispute_outcomes.py`

**Interfaces:**
- Consumes: `DisputeResolved` (governance.schemas, Task 3), `DisputeResolution` and `DisputeTargetType` (governance.service), `recalculate(session, worker_id, *, policy, trigger_event_id)` (standing.recalculation), `active_tiering` (governance.service).
- Produces:
  - `EngagementRepository.feedback_for_update(feedback_id) -> Feedback | None`.
  - `engagements.queries.engagement_feedback_id(session, engagement_id) -> UUID | None`.
  - `engagements.feedback.exclude_feedback(session, feedback_id, *, reason) -> bool`. It returns True only if this call changed the flag. It writes audit `feedback.excluded_from_standing`.
  - Both functions are exported from `engagements.service`.
  - Handler `standing.apply_dispute_outcome` on `DisputeResolved`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/standing/test_dispute_outcomes.py`:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.service import exclude_feedback
from app.modules.governance.service import active_tiering
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import StandingTier
from app.modules.passport.models import Worker
from app.modules.standing.models import StandingChange
from app.modules.standing.recalculation import recalculate
from tests.support import (
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

Drain = Callable[[], Awaitable[None]]


@dataclass
class Rated:
    worker: Worker
    account: UserAccount
    engagement: Engagement
    feedback: Feedback


async def _rated_worker(session: AsyncSession) -> Rated:
    """A tier_1 worker: one completed engagement with positive feedback."""
    pm = await make_user(session, role=UserRole.PM)
    worker, account = await make_worker(session)
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    feedback = await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1
    return Rated(worker=worker, account=account, engagement=engagement, feedback=feedback)


async def _decide(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    rated: Rated,
    target: tuple[str, UUID],
    resolution: str,
) -> None:
    target_type, target_id = target
    filed = await client.post(
        "/api/v1/disputes",
        json={
            "target_type": target_type,
            "target_id": str(target_id),
            "reason": "This record is not accurate.",
        },
        headers=bearer(settings, rated.account),
    )
    assert filed.status_code == 201, filed.json()
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    decided = await client.patch(
        f"/api/v1/disputes/{filed.json()['id']}",
        json={"resolution": resolution, "resolution_notes": "Reviewed with the project PM."},
        headers=bearer(settings, ops),
    )
    assert decided.status_code == 200, decided.json()


async def _change_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(StandingChange)) or 0)


async def test_an_upheld_feedback_dispute_stops_it_counting(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)

    await _decide(client, session, settings, rated, ("feedback", rated.feedback.id), "upheld")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is True
    assert rated.worker.standing_tier is StandingTier.UNRATED
    latest = (
        await session.scalars(select(StandingChange).order_by(StandingChange.created_at.desc()))
    ).first()
    resolved = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.dispute_resolved")
        )
    ).one()
    assert latest is not None
    assert (latest.new_tier, latest.trigger_event_id) == (StandingTier.UNRATED, resolved.event_id)
    audit = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "feedback.excluded_from_standing")
        )
    ).one()
    assert (audit.target_id, audit.reason) == (rated.engagement.id, "dispute_upheld")


async def test_a_rejected_dispute_changes_nothing(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)

    await _decide(client, session, settings, rated, ("feedback", rated.feedback.id), "rejected")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is False
    assert rated.worker.standing_tier is StandingTier.TIER_1


async def test_an_upheld_engagement_dispute_excludes_its_feedback(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)

    await _decide(
        client, session, settings, rated, ("engagement", rated.engagement.id), "upheld"
    )
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is True
    assert rated.worker.standing_tier is StandingTier.UNRATED


async def test_an_upheld_standing_change_dispute_leaves_the_data_alone(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    rated = await _rated_worker(session)
    change = (await session.scalars(select(StandingChange))).one()

    await _decide(client, session, settings, rated, ("standing_change", change.id), "upheld")
    await drain()

    await session.refresh(rated.feedback)
    await session.refresh(rated.worker)
    assert rated.feedback.excluded_from_standing is False
    assert rated.worker.standing_tier is StandingTier.TIER_1
    assert await _change_count(session) == 1


async def test_excluding_twice_changes_nothing_more(session: AsyncSession) -> None:
    rated = await _rated_worker(session)

    first = await exclude_feedback(session, rated.feedback.id, reason="dispute_upheld")
    second = await exclude_feedback(session, rated.feedback.id, reason="dispute_upheld")
    await session.commit()

    assert (first, second) == (True, False)
    audits = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "feedback.excluded_from_standing")
        )
    ).all()
    assert len(audits) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/standing/test_dispute_outcomes.py -v`
Expected: FAIL with `ImportError: cannot import name 'exclude_feedback'`.

- [ ] **Step 3: Add the engagements side**

Append a method to `EngagementRepository` in `backend/app/modules/engagements/repository.py`:

```python
    async def feedback_for_update(self, feedback_id: UUID) -> Feedback | None:
        return await self.session.scalar(
            select(Feedback).where(Feedback.id == feedback_id).with_for_update()
        )
```

Append to `backend/app/modules/engagements/queries.py`:

```python
async def engagement_feedback_id(session: AsyncSession, engagement_id: UUID) -> UUID | None:
    return await session.scalar(select(Feedback.id).where(Feedback.engagement_id == engagement_id))
```

Append to `backend/app/modules/engagements/feedback.py`:

```python
async def exclude_feedback(session: AsyncSession, feedback_id: UUID, *, reason: str) -> bool:
    """Spec §2.2 #8: an upheld dispute stops the record counting toward
    standing. True only if this call changed it."""
    feedback = await EngagementRepository(session).feedback_for_update(feedback_id)
    if feedback is None or feedback.excluded_from_standing:
        return False
    feedback.excluded_from_standing = True
    await write_audit(
        session,
        actor=None,
        action="feedback.excluded_from_standing",
        target_type="engagement",
        target_id=feedback.engagement_id,
        before={"excluded_from_standing": False},
        after={"excluded_from_standing": True},
        reason=reason,
    )
    return True
```

In `backend/app/modules/engagements/service.py`:
- add `engagement_feedback_id` to the `queries` import;
- add `from app.modules.engagements.feedback import exclude_feedback`;
- add both names to `__all__`.

- [ ] **Step 4: Add the standing handler**

In `backend/app/modules/standing/handlers.py`, add these imports:

```python
from app.modules.engagements.service import engagement_feedback_id, exclude_feedback
from app.modules.governance.schemas import DisputeResolved, PolicyActivated
from app.modules.governance.service import DisputeResolution, DisputeTargetType, active_tiering
```

(replacing the existing single-name `governance.schemas` and `governance.service` imports), and add this at the end of `register`:

```python
    async def apply_dispute_outcome(session: AsyncSession, payload: dict[str, Any]) -> None:
        """Spec §2.2 #8. An upheld standing-change dispute changes no data
        here: the rules are deterministic, so People Ops override the tier."""
        if payload["resolution"] != DisputeResolution.UPHELD.value:
            return
        target_id = UUID(payload["target_id"])
        if payload["target_type"] == DisputeTargetType.FEEDBACK.value:
            feedback_id: UUID | None = target_id
        elif payload["target_type"] == DisputeTargetType.ENGAGEMENT.value:
            feedback_id = await engagement_feedback_id(session, target_id)
        else:
            return
        if feedback_id is None or not await exclude_feedback(
            session, feedback_id, reason="dispute_upheld"
        ):
            return
        await recalculate(
            session,
            UUID(payload["worker_id"]),
            policy=await active_tiering(session),
            trigger_event_id=get_event_id(),
        )

    registry.register(DisputeResolved, "standing.apply_dispute_outcome", apply_dispute_outcome)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/api/standing tests/api/governance tests/api/engagements -v`
Expected: PASS.

- [ ] **Step 6: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app/modules/engagements app/modules/standing tests/api/standing/test_dispute_outcomes.py
git commit -m "feat(standing): an upheld dispute stops feedback counting

DisputeResolved(upheld) on feedback, or on an engagement with feedback, sets
excluded_from_standing and recalculates the worker (spec §2.2 #8).

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 5: Standing overrides

People Ops change a worker's tier by hand, with a required reason (spec §7.2, §8.1). The override is written as a `standing_changes` row with `actor_id` and `override_reason`, together with the tier the rules gave at that moment.

Recalculation leaves an override alone until the rules' own verdict differs from that recorded tier. Without this, the next feedback or the nightly run would undo it.

The route lives in `standing`, which owns `standing_changes`. It puts the worker in the path: `POST /workers/{worker_id}/standing-overrides`.

**Files:**
- Create: `backend/app/modules/standing/overrides.py`
- Modify: `backend/app/modules/standing/schemas.py`, `repository.py`, `recalculation.py`, `router.py`
- Test: `backend/tests/api/standing/test_overrides.py`

**Interfaces:**
- Consumes: `lock_standing_tier`, `set_standing_tier`, `StandingTier` (passport.service); `standing_records` (engagements.service); `active_tiering` (governance.service); `evaluate` (standing.rules); `StandingChangeRead` (with `id`, Task 3).
- Produces:
  - `standing.schemas.StandingOverrideCreate(tier: StandingTier, reason: str 10–500)`.
  - `StandingChangeRepository.latest_for_worker(worker_id) -> StandingChange | None`.
  - `standing.overrides.override_standing(session, actor, worker_id, data) -> StandingChange`.
    - Its `contributing_factors` include `policy_version` and `evaluated_tier`.
    - It writes audit `standing.overridden` with the reason.
    - It emits `StandingChanged`.
  - Route `POST /api/v1/workers/{worker_id}/standing-overrides` (permission `standing:override`, visibility DETAIL), returning 201 with a `StandingChangeRead`.
  - `recalculate` returns None while the latest change is an override whose `evaluated_tier` equals the current evaluation.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/standing/test_overrides.py`:

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
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import StandingTier
from app.modules.standing.models import StandingChange
from app.modules.standing.recalculation import recalculate
from app.modules.standing.service import recalculate_all_standing
from tests.support import (
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

REASON = "Verified strong references from two past clients."


def _url(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/standing-overrides"


async def test_people_ops_override_a_tier_with_a_reason(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url(worker.id), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["previous_tier"], body["new_tier"], body["automated"]) == (
        "unrated",
        "tier_2",
        False,
    )
    assert body["override_reason"] == REASON
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_2
    change = (await session.scalars(select(StandingChange))).one()
    assert (change.actor_id, change.contributing_factors["evaluated_tier"]) == (ops.id, "unrated")
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "standing.overridden"))
    ).one()
    assert (audit.reason, audit.before, audit.after) == (
        REASON,
        {"tier": "unrated"},
        {"tier": "tier_2", "evaluated_tier": "unrated"},
    )
    events = (await session.scalars(select(OutboxEvent.event_type))).all()
    assert events == ["standing.standing_changed"]
    explanation = (
        await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
    ).json()
    assert explanation["tier"] == "tier_2"
    assert explanation["history"][0]["automated"] is False


@pytest.mark.parametrize(
    ("role", "body", "status", "code"),
    [
        (UserRole.PM, {"tier": "tier_2", "reason": REASON}, 403, "permission_denied"),
        (UserRole.PEOPLE_OPS, {"tier": "tier_2", "reason": "short"}, 422, "validation_error"),
        (UserRole.PEOPLE_OPS, {"tier": "unrated", "reason": REASON}, 409, "standing_unchanged"),
    ],
)
async def test_overrides_are_refused_when_they_should_be(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    role: UserRole,
    body: dict[str, str],
    status: int,
    code: str,
) -> None:
    worker, _ = await make_worker(session)
    user = await make_user(session, role=role)

    response = await client.post(_url(worker.id), json=body, headers=bearer(settings, user))

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert (await session.scalars(select(StandingChange))).all() == []


async def test_overriding_an_unknown_worker_is_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url(uuid4()), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )

    assert (response.status_code, response.json()["code"]) == (404, "worker_not_found")


async def test_an_override_survives_the_nightly_re_evaluation(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await client.post(
        _url(worker.id), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )

    await recalculate_all_standing(session)
    await session.commit()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_2
    assert len((await session.scalars(select(StandingChange))).all()) == 1


async def test_an_override_yields_once_the_rules_verdict_moves(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)
    await client.post(
        _url(worker.id), json={"tier": "tier_2", "reason": REASON}, headers=bearer(settings, ops)
    )
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    change = await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1
    assert change is not None
    assert (change.previous_tier, change.new_tier, change.actor_id) == (
        StandingTier.TIER_2,
        StandingTier.TIER_1,
        None,
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/standing/test_overrides.py -v`
Expected: FAIL with 404 (the route does not exist yet).

- [ ] **Step 3: Add the schema and the repository method**

In `backend/app/modules/standing/schemas.py`, change the pydantic import to `from pydantic import BaseModel, ConfigDict, Field` and append:

```python
class StandingOverrideCreate(BaseModel):
    """Spec §7.2 / §8.1: a manual tier change always carries a reason."""

    model_config = ConfigDict(extra="forbid")

    tier: StandingTier
    reason: str = Field(min_length=10, max_length=500)
```

Add to `StandingChangeRepository` in `backend/app/modules/standing/repository.py`:

```python
    async def latest_for_worker(self, worker_id: UUID) -> StandingChange | None:
        changes = await self.list_for_worker(worker_id, 1)
        return changes[0] if changes else None
```

- [ ] **Step 4: Keep overrides in place during recalculation**

In `backend/app/modules/standing/recalculation.py`, replace the part of `recalculate` from `if new_tier is current:` down to the `StandingChangeRepository(session).add(` line with:

```python
    if new_tier is current:
        return None
    changes = StandingChangeRepository(session)
    latest = await changes.latest_for_worker(worker_id)
    if (
        latest is not None
        and latest.actor_id is not None
        and latest.contributing_factors.get("evaluated_tier") == evaluation.tier
    ):
        # A People Ops override holds until the rules' own verdict moves.
        return None
    change = changes.add(
```

The rest of the `StandingChange(...)` construction is unchanged.

- [ ] **Step 5: Write the override service**

`backend/app/modules/standing/overrides.py`:

```python
"""Manual tier changes by People Ops (spec §7.2, §8.1)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.service import active_tiering
from app.modules.passport.service import lock_standing_tier, set_standing_tier
from app.modules.standing.models import StandingChange
from app.modules.standing.repository import StandingChangeRepository
from app.modules.standing.rules import evaluate
from app.modules.standing.schemas import StandingChanged, StandingOverrideCreate


async def override_standing(
    session: AsyncSession, actor: Actor, worker_id: UUID, data: StandingOverrideCreate
) -> StandingChange:
    """Stores the rules' verdict next to the override, so recalculation can
    leave the override alone until that verdict changes."""
    current = await lock_standing_tier(session, worker_id)
    if current is None:
        raise NotFound("Worker not found", code="worker_not_found")
    if data.tier is current:
        raise Conflict("The worker already has this tier", code="standing_unchanged")
    policy = await active_tiering(session)
    evaluation = evaluate(await standing_records(session, worker_id), policy.rules, utcnow().date())
    change = StandingChangeRepository(session).add(
        StandingChange(
            worker_id=worker_id,
            previous_tier=current,
            new_tier=data.tier,
            contributing_factors={
                **evaluation.factors(),
                "policy_version": policy.version,
                "evaluated_tier": evaluation.tier,
            },
            policy_version_id=policy.id,
            actor_id=actor.user_id,
            override_reason=data.reason,
        )
    )
    await set_standing_tier(session, worker_id, data.tier)
    await session.flush()
    await write_audit(
        session,
        actor=actor,
        action="standing.overridden",
        target_type="worker",
        target_id=worker_id,
        before={"tier": current.value},
        after={"tier": data.tier.value, "evaluated_tier": evaluation.tier},
        reason=data.reason,
    )
    await emit_event(
        session,
        StandingChanged(
            aggregate_id=worker_id,
            previous_tier=current,
            new_tier=data.tier,
            policy_version=policy.version,
        ),
    )
    return change
```

- [ ] **Step 6: Add the route**

In `backend/app/modules/standing/router.py`, replace the imports with:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.errors import Forbidden
from app.modules.identity.service import (
    CurrentActor,
    Permission,
    Visibility,
    require_permission,
    require_visibility,
)
from app.modules.standing.explanation import standing_explanation
from app.modules.standing.overrides import override_standing
from app.modules.standing.schemas import (
    StandingChangeRead,
    StandingExplanation,
    StandingOverrideCreate,
)
```

After `router = …`, add:

```python
StandingOverrider = Annotated[Actor, Depends(require_permission(Permission.STANDING_OVERRIDE))]
```

and append:

```python
@router.post("/workers/{worker_id}/standing-overrides", status_code=201)
async def override_worker_standing(
    worker_id: UUID,
    body: StandingOverrideCreate,
    actor: StandingOverrider,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> StandingChangeRead:
    change = await override_standing(session, actor, worker_id, body)
    return StandingChangeRead(
        id=change.id,
        previous_tier=change.previous_tier,
        new_tier=change.new_tier,
        factors=change.contributing_factors,
        policy_version=change.contributing_factors["policy_version"],
        automated=False,
        override_reason=change.override_reason,
        occurred_at=change.created_at,
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/api/standing tests/api/test_visibility_guard.py -v`
Expected: PASS. The existing recalculation tests still pass: they write no overrides.

- [ ] **Step 8: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app/modules/standing tests/api/standing/test_overrides.py
git commit -m "feat(standing): People Ops standing overrides

POST /workers/{id}/standing-overrides records a manual tier with a reason.
The override holds until the rules' own verdict for the worker moves.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 6: Worker and PM notifications

Spec §7.7 `notify_worker` and `notify_feedback_due`. Four mails are sent, each in the recipient's locale:
- The worker hears when their engagement becomes active (`EngagementActivated`).
- Every active PM staffed on the project hears that feedback is due (`EngagementCompleted`), unless feedback is already in.
- The worker hears when their standing changes (`StandingChanged`, including overrides).
- The worker hears how their dispute ended (`DisputeResolved`), with People Ops' notes.

The notes are read from the dispute row, never from the event payload. A recipient with no account is skipped without error.

**Files:**
- Create: `backend/app/modules/engagements/notifications.py`, `backend/app/modules/standing/notifications.py`, `backend/app/modules/governance/notifications.py`, `backend/app/modules/governance/handlers.py`
- Modify: `backend/app/core/i18n.py`, `backend/app/modules/engagements/handlers.py`, `backend/app/modules/standing/handlers.py`, `backend/app/wiring.py`
- Test: `backend/tests/api/test_notifications.py`

**Interfaces:**
- Consumes:
  - `identity.service`: `worker_contact(session, worker_id) -> AccountContact | None`, `account_contact(session, user_id)`, `active_pm_ids(session, ids)`.
  - `passport.service.worker_name(session, worker_id) -> str | None`.
  - `DisputeRepository.get` (Task 3).
  - `Mailer` (app.core.mail).
- Produces:
  - `engagements.notifications.notify_engagement_confirmed(session, mailer, engagement_id) -> bool` and `notify_feedback_due(session, mailer, engagement_id) -> int`.
  - `standing.notifications.notify_standing_changed(session, mailer, worker_id, *, previous: str, new: str) -> bool`.
  - `governance.notifications.notify_dispute_resolved(session, mailer, dispute_id) -> bool`.
  - Register signatures:
    - `engagements.handlers.register(registry, *, esign, payroll, mailer)`
    - `standing.handlers.register(registry, *, mailer)`
    - `governance.handlers.register(registry, *, mailer)`
  - Handlers:
    - `engagements.notify_worker` (`EngagementActivated`)
    - `engagements.notify_feedback_due` (`EngagementCompleted`)
    - `standing.notify_worker` (`StandingChanged`)
    - `governance.notify_worker` (`DisputeResolved`)
  - i18n keys, in both locales:
    - `engagement_confirmed.subject` and `.body`
    - `feedback_due.subject` and `.body`
    - `standing_changed.subject` and `.body`
    - `tier.unrated`, `tier.tier_1`, `tier.tier_2`
    - `dispute_resolved.subject`, `dispute_resolved.body.upheld` and `dispute_resolved.body.rejected`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_notifications.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.time import utcnow
from app.modules.engagements.contracts import activate_due
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.notifications import notify_feedback_due
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import WorkerType
from app.modules.passport.models import Worker
from app.modules.standing.recalculation import recalculate
from tests.support import (
    RecordingMailer,
    bearer,
    make_dispute,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

Drain = Callable[[], Awaitable[None]]


async def _start_today(session: AsyncSession, worker_id: UUID, project_id: UUID) -> None:
    engagement = await make_engagement(
        session,
        worker_id=worker_id,
        project_id=project_id,
        status=EngagementStatus.SIGNED,
        start_date=utcnow().date(),
    )
    engagement.signed_at = utcnow()
    await session.commit()
    assert await activate_due(session) == 1
    await session.commit()


async def test_the_worker_hears_when_their_engagement_starts(
    session: AsyncSession, drain: Drain, mailer: RecordingMailer
) -> None:
    worker, _ = await make_worker(session, email="kofi@example.com", locale="fr")
    project = await make_project(session, name="Projet Volta")

    await _start_today(session, worker.id, project.id)
    await drain()

    (mail,) = [m for m in mailer.sent if m["to"] == "kofi@example.com"]
    assert mail["subject"] == "Votre mission sur Projet Volta a commencé"
    assert utcnow().date().isoformat() in mail["body"]


async def test_a_worker_without_an_account_gets_no_mail_and_no_error(
    session: AsyncSession, drain: Drain, mailer: RecordingMailer
) -> None:
    worker = Worker(full_name="No Account", worker_type=WorkerType.FREELANCER, data_region="GH")
    session.add(worker)
    await session.flush()
    project = await make_project(session)

    await _start_today(session, worker.id, project.id)
    await drain()

    assert mailer.sent == []


async def test_staffed_pms_hear_that_feedback_is_due(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    ama = await make_user(session, role=UserRole.PM, email="ama@bonarda.works")
    gone = await make_user(
        session, role=UserRole.PM, email="gone@bonarda.works", status=AccountStatus.REVOKED
    )
    worker, _ = await make_worker(session, full_name="Kofi Mensah")
    project = await make_project(session, staff=[ama, gone], name="Project Volta")
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        status=EngagementStatus.ACTIVE,
        start_date=utcnow().date() - timedelta(days=30),
    )

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, ama)
    )
    await drain()

    assert response.status_code == 200
    due = [m for m in mailer.sent if m["subject"].startswith("Feedback due")]
    assert [m["to"] for m in due] == ["ama@bonarda.works"]
    assert due[0]["subject"] == "Feedback due for Kofi Mensah on Project Volta"


async def test_no_feedback_reminder_once_feedback_is_in(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session)
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    mailer = RecordingMailer()

    assert await notify_feedback_due(session, mailer, engagement.id) == 0
    assert mailer.sent == []


async def test_the_worker_hears_when_their_standing_changes(
    session: AsyncSession, drain: Drain, mailer: RecordingMailer
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session, email="kofi@example.com", locale="fr")
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()
    await drain()

    (mail,) = [m for m in mailer.sent if m["to"] == "kofi@example.com"]
    assert mail["subject"] == "Votre statut Bonarda a changé"
    assert "Non classé" in mail["body"]
    assert "Niveau 1" in mail["body"]


async def test_the_worker_hears_how_their_dispute_ended(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    worker, _ = await make_worker(session, email="kofi@example.com")
    dispute = await make_dispute(session, worker_id=worker.id, due_at=utcnow() + timedelta(days=30))
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    notes = "The feedback was written for a different engagement."

    response = await client.patch(
        f"/api/v1/disputes/{dispute.id}",
        json={"resolution": "rejected", "resolution_notes": notes},
        headers=bearer(settings, ops),
    )
    await drain()

    assert response.status_code == 200
    (mail,) = [m for m in mailer.sent if m["to"] == "kofi@example.com"]
    assert mail["subject"] == "Your dispute has been resolved"
    assert "did not uphold" in mail["body"]
    assert notes in mail["body"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/test_notifications.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.engagements.notifications'`.

- [ ] **Step 3: Add the messages**

In `backend/app/core/i18n.py`, add these entries to the `"en"` catalog after `"invitation.body"`:

```python
        "engagement_confirmed.subject": "Your engagement on {project} has started",
        "engagement_confirmed.body": (
            "Your contract for {project} is signed and your engagement is active from "
            "{start_date}. You can see it on your Bonarda passport."
        ),
        "feedback_due.subject": "Feedback due for {worker} on {project}",
        "feedback_due.body": (
            "{worker}'s engagement on {project} is complete. Please submit feedback: "
            "it is how their standing reflects their work."
        ),
        "standing_changed.subject": "Your Bonarda standing has changed",
        "standing_changed.body": (
            "Your standing changed from {previous} to {tier}. Your passport shows the "
            "signals and the policy behind it. If you think it is wrong, you can dispute "
            "it from your passport."
        ),
        "tier.unrated": "Unrated",
        "tier.tier_1": "Tier 1",
        "tier.tier_2": "Tier 2",
        "dispute_resolved.subject": "Your dispute has been resolved",
        "dispute_resolved.body.upheld": "People Ops upheld your dispute.\n\nTheir notes:\n{notes}",
        "dispute_resolved.body.rejected": (
            "People Ops reviewed your dispute and did not uphold it.\n\nTheir notes:\n{notes}"
        ),
```

and these to the `"fr"` catalog after its `"invitation.body"`:

```python
        "engagement_confirmed.subject": "Votre mission sur {project} a commencé",
        "engagement_confirmed.body": (
            "Votre contrat pour {project} est signé et votre mission est active à partir "
            "du {start_date}. Vous la retrouvez dans votre passeport Bonarda."
        ),
        "feedback_due.subject": "Retour attendu pour {worker} sur {project}",
        "feedback_due.body": (
            "La mission de {worker} sur {project} est terminée. Merci de soumettre votre "
            "retour : c'est ainsi que son statut reflète son travail."
        ),
        "standing_changed.subject": "Votre statut Bonarda a changé",
        "standing_changed.body": (
            "Votre statut est passé de {previous} à {tier}. Votre passeport présente les "
            "signaux et la politique qui l'expliquent. Si vous pensez qu'il est erroné, "
            "vous pouvez le contester depuis votre passeport."
        ),
        "tier.unrated": "Non classé",
        "tier.tier_1": "Niveau 1",
        "tier.tier_2": "Niveau 2",
        "dispute_resolved.subject": "Votre contestation a été traitée",
        "dispute_resolved.body.upheld": (
            "L'équipe People Ops a donné raison à votre contestation.\n\n"
            "Ses remarques :\n{notes}"
        ),
        "dispute_resolved.body.rejected": (
            "L'équipe People Ops a examiné votre contestation et ne l'a pas retenue.\n\n"
            "Ses remarques :\n{notes}"
        ),
```

- [ ] **Step 4: Write the three notification modules**

`backend/app/modules/engagements/notifications.py`:

```python
"""Mail the engagements module sends (spec §7.7 notify_worker, notify_feedback_due).
Recipients without an account are skipped: the event must never dead-letter."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.identity.service import account_contact, active_pm_ids, worker_contact
from app.modules.passport.service import worker_name


async def notify_engagement_confirmed(
    session: AsyncSession, mailer: Mailer, engagement_id: UUID
) -> bool:
    """To the worker once their engagement is active. False if nobody was told."""
    engagement = await EngagementRepository(session).get(engagement_id)
    if engagement is None:
        return False
    contact = await worker_contact(session, engagement.worker_id)
    project = await ProjectRepository(session).get(engagement.project_id)
    if contact is None or project is None:
        return False
    await mailer.send(
        to=contact.email,
        subject=t("engagement_confirmed.subject", contact.locale, project=project.name),
        body=t(
            "engagement_confirmed.body",
            contact.locale,
            project=project.name,
            start_date=engagement.start_date.isoformat(),
        ),
    )
    return True


async def notify_feedback_due(session: AsyncSession, mailer: Mailer, engagement_id: UUID) -> int:
    """To every active PM staffed on the project, unless feedback is already
    in. Returns how many PMs were told."""
    engagements = EngagementRepository(session)
    engagement = await engagements.get(engagement_id)
    if engagement is None or engagement.id in await engagements.feedback_for([engagement.id]):
        return 0
    projects = ProjectRepository(session)
    project = await projects.get(engagement.project_id)
    if project is None:
        return 0
    name = await worker_name(session, engagement.worker_id) or ""
    pm_ids = await active_pm_ids(session, await projects.active_staff_ids(project.id))
    for user_id in sorted(pm_ids, key=str):
        contact = await account_contact(session, user_id)
        await mailer.send(
            to=contact.email,
            subject=t("feedback_due.subject", contact.locale, worker=name, project=project.name),
            body=t("feedback_due.body", contact.locale, worker=name, project=project.name),
        )
    return len(pm_ids)
```

`backend/app/modules/standing/notifications.py`:

```python
"""Tells a worker their tier changed (spec §7.7 notify_worker on StandingChanged)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.identity.service import worker_contact


async def notify_standing_changed(
    session: AsyncSession, mailer: Mailer, worker_id: UUID, *, previous: str, new: str
) -> bool:
    contact = await worker_contact(session, worker_id)
    if contact is None:
        return False
    locale = contact.locale
    await mailer.send(
        to=contact.email,
        subject=t("standing_changed.subject", locale),
        body=t(
            "standing_changed.body",
            locale,
            previous=t(f"tier.{previous}", locale),
            tier=t(f"tier.{new}", locale),
        ),
    )
    return True
```

`backend/app/modules/governance/notifications.py`:

```python
"""Tells a worker how their dispute ended (spec §7.7 DisputeResolved → notify_worker).
The notes come from the dispute row: outbox payloads carry no free text."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.governance.repository import DisputeRepository
from app.modules.identity.service import worker_contact


async def notify_dispute_resolved(session: AsyncSession, mailer: Mailer, dispute_id: UUID) -> bool:
    dispute = await DisputeRepository(session).get(dispute_id)
    if dispute is None or dispute.resolution is None:
        return False
    contact = await worker_contact(session, dispute.worker_id)
    if contact is None:
        return False
    await mailer.send(
        to=contact.email,
        subject=t("dispute_resolved.subject", contact.locale),
        body=t(
            f"dispute_resolved.body.{dispute.resolution.value}",
            contact.locale,
            notes=dispute.resolution_notes or "",
        ),
    )
    return True
```

- [ ] **Step 5: Register the handlers**

In `backend/app/modules/engagements/handlers.py`:
- add `from app.core.mail import Mailer`;
- add `from app.modules.engagements.notifications import notify_engagement_confirmed, notify_feedback_due`;
- change the signature to `def register(registry: HandlerRegistry, *, esign: EsignAdapter, payroll: PayrollAdapter, mailer: Mailer) -> None:`.

Then add at the end of `register`:

```python
    async def confirm(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_engagement_confirmed(session, mailer, UUID(payload["aggregate_id"]))

    async def feedback_due(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_feedback_due(session, mailer, UUID(payload["aggregate_id"]))

    registry.register(EngagementActivated, "engagements.notify_worker", confirm)
    registry.register(EngagementCompleted, "engagements.notify_feedback_due", feedback_due)
```

In `backend/app/modules/standing/handlers.py`:
- add `from app.core.mail import Mailer`, `from app.modules.standing.notifications import notify_standing_changed` and `from app.modules.standing.schemas import StandingChanged`;
- change the signature to `def register(registry: HandlerRegistry, *, mailer: Mailer) -> None:`.

Then add at the end of `register`:

```python
    async def notify_worker(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_standing_changed(
            session,
            mailer,
            UUID(payload["aggregate_id"]),
            previous=payload["previous_tier"],
            new=payload["new_tier"],
        )

    registry.register(StandingChanged, "standing.notify_worker", notify_worker)
```

`backend/app/modules/governance/handlers.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.governance.notifications import notify_dispute_resolved
from app.modules.governance.schemas import DisputeResolved


def register(registry: HandlerRegistry, *, mailer: Mailer) -> None:
    async def notify_worker(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_dispute_resolved(session, mailer, UUID(payload["aggregate_id"]))

    registry.register(DisputeResolved, "governance.notify_worker", notify_worker)
```

In `backend/app/wiring.py`, add `from app.modules.governance import handlers as governance_handlers` and make `build_registry` read:

```python
def build_registry(deps: HandlerDeps) -> HandlerRegistry:
    registry = HandlerRegistry()
    identity_handlers.register(
        registry, redis=deps.redis, settings=deps.settings, mailer=deps.mailer
    )
    engagements_handlers.register(
        registry, esign=deps.esign, payroll=deps.payroll, mailer=deps.mailer
    )
    standing_handlers.register(registry, mailer=deps.mailer)
    governance_handlers.register(registry, mailer=deps.mailer)
    roster_handlers.register(registry)
    return registry
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/api/test_notifications.py tests/unit/test_i18n.py tests/api -v`
Expected: PASS. Existing tests that assert on `mailer.sent` only look at sign-in and invitation mail, so the new mails do not change them. If one does, filter its assertion by recipient or subject; do not remove a notification.

- [ ] **Step 7: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests/api/test_notifications.py
git commit -m "feat: notify workers and PMs of engagement, standing and dispute events

Workers hear when an engagement starts, when their standing changes and how
a dispute ended; staffed PMs hear when feedback is due (spec §7.7). Mail is
localized and skipped for recipients without an account.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 7: The daily dispute SLA digest

Spec §7.7 `dispute_sla_reminder`, daily at 08:00 UTC. Every active People Ops account gets one digest of the open disputes that are overdue or due within `dispute_reminder_days` (default 3), oldest due first. Nothing is sent when nothing is due.

**Files:**
- Create: `backend/app/modules/governance/reminders.py`
- Modify: `backend/app/core/i18n.py`, `backend/app/core/config.py`, `backend/app/modules/identity/accounts.py`, `backend/app/modules/identity/service.py`, `backend/app/modules/governance/service.py`, `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`
- Test: `backend/tests/api/governance/test_dispute_sla.py`

**Interfaces:**
- Consumes: `DisputeRepository.open_due_before(cutoff)` (Task 3), `make_dispute` (tests.support).
- Produces:
  - `identity.accounts.staff_contacts(session, role: UserRole) -> list[AccountContact]`: active accounts with that role, ordered by email. It is exported from `identity.service`.
  - `governance.reminders.remind_due_disputes(session, mailer, *, now, warn_days) -> int`: how many disputes were listed. It is exported from `governance.service`.
  - `Settings.dispute_reminder_days = 3`.
  - Arq cron `remind_dispute_sla` at 08:00 UTC. The worker's `ctx` gains `"settings"` and `"mailer"`; the handler registry uses that same mailer.
  - i18n keys `dispute_sla.subject`, `dispute_sla.body`, `dispute_sla.overdue` and `dispute_sla.due_soon`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/governance/test_dispute_sla.py`:

```python
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.time import utcnow
from app.modules.governance.service import remind_due_disputes
from app.worker import jobs
from tests.support import RecordingMailer, make_dispute, make_user, make_worker


async def test_people_ops_get_one_digest_of_overdue_and_due_soon_disputes(
    session: AsyncSession,
) -> None:
    now = utcnow()
    worker, _ = await make_worker(session)
    overdue = await make_dispute(session, worker_id=worker.id, due_at=now - timedelta(days=1))
    soon = await make_dispute(session, worker_id=worker.id, due_at=now + timedelta(days=2))
    later = await make_dispute(session, worker_id=worker.id, due_at=now + timedelta(days=20))
    closed = await make_dispute(
        session, worker_id=worker.id, due_at=now - timedelta(days=5), resolved=True
    )
    await make_user(session, role=UserRole.PEOPLE_OPS, email="ops@bonarda.works")
    await make_user(
        session,
        role=UserRole.PEOPLE_OPS,
        email="gone@bonarda.works",
        status=AccountStatus.REVOKED,
    )
    await make_user(session, role=UserRole.PM, email="pm@bonarda.works")
    mailer = RecordingMailer()

    listed = await remind_due_disputes(session, mailer, now=now, warn_days=3)

    assert listed == 2
    (mail,) = mailer.sent
    assert mail["to"] == "ops@bonarda.works"
    assert mail["subject"] == "Disputes: 1 overdue, 1 due soon"
    body = mail["body"]
    assert body.index(str(overdue.id)) < body.index(str(soon.id))
    assert str(later.id) not in body
    assert str(closed.id) not in body


async def test_no_digest_when_nothing_is_due(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    await make_dispute(session, worker_id=worker.id, due_at=utcnow() + timedelta(days=20))
    await make_user(session, role=UserRole.PEOPLE_OPS)
    mailer = RecordingMailer()

    assert await remind_due_disputes(session, mailer, now=utcnow(), warn_days=3) == 0
    assert mailer.sent == []


async def test_the_daily_job_uses_the_worker_mailer_and_settings(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    await make_dispute(session, worker_id=worker.id, due_at=utcnow() + timedelta(days=4))
    await make_user(session, role=UserRole.PEOPLE_OPS)
    mailer = RecordingMailer()
    ctx = {
        "sessionmaker": sessionmaker,
        "mailer": mailer,
        "settings": settings.model_copy(update={"dispute_reminder_days": 5}),
    }

    assert await jobs.remind_dispute_sla(ctx) == 1
    assert len(mailer.sent) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/governance/test_dispute_sla.py -v`
Expected: FAIL with `ImportError: cannot import name 'remind_due_disputes'`.

- [ ] **Step 3: Add the messages and the setting**

In `backend/app/core/i18n.py`, add to the `"en"` catalog:

```python
        "dispute_sla.subject": "Disputes: {overdue} overdue, {due_soon} due soon",
        "dispute_sla.body": "These open disputes need a decision:\n\n{lines}",
        "dispute_sla.overdue": "overdue",
        "dispute_sla.due_soon": "due soon",
```

and to the `"fr"` catalog:

```python
        "dispute_sla.subject": "Contestations : {overdue} en retard, {due_soon} bientôt dues",
        "dispute_sla.body": "Ces contestations ouvertes attendent une décision :\n\n{lines}",
        "dispute_sla.overdue": "en retard",
        "dispute_sla.due_soon": "bientôt due",
```

In `backend/app/core/config.py`, after `dispute_sla_days`:

```python
    # The daily digest lists open disputes due within this many days.
    dispute_reminder_days: int = 3
```

- [ ] **Step 4: Add the contact lookup**

Append to `backend/app/modules/identity/accounts.py`:

```python
async def staff_contacts(session: AsyncSession, role: UserRole) -> list[AccountContact]:
    """Active accounts holding `role`, for operational mail such as the
    dispute digest."""
    rows = await session.scalars(
        select(UserAccount)
        .where(UserAccount.role == role, UserAccount.status == AccountStatus.ACTIVE)
        .order_by(UserAccount.email)
    )
    return [AccountContact(email=user.email, locale=user.locale) for user in rows.all()]
```

Add `staff_contacts` to the `accounts` import in `backend/app/modules/identity/service.py`, and to its `__all__`.

- [ ] **Step 5: Write the digest**

`backend/app/modules/governance/reminders.py`:

```python
"""The daily dispute SLA digest to People Ops (spec §7.7 dispute_sla_reminder)."""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.governance.models import Dispute
from app.modules.governance.repository import DisputeRepository
from app.modules.identity.service import staff_contacts


def _line(dispute: Dispute, now: datetime, locale: str) -> str:
    state = t("dispute_sla.overdue" if dispute.due_at <= now else "dispute_sla.due_soon", locale)
    return f"- {dispute.id}: {state} ({dispute.due_at.date().isoformat()})"


async def remind_due_disputes(
    session: AsyncSession, mailer: Mailer, *, now: datetime, warn_days: int
) -> int:
    """Mails every active People Ops account one digest of the open disputes
    that are overdue or due within `warn_days`. Returns how many it listed."""
    due = await DisputeRepository(session).open_due_before(now + timedelta(days=warn_days))
    if not due:
        return 0
    overdue = sum(1 for dispute in due if dispute.due_at <= now)
    for contact in await staff_contacts(session, UserRole.PEOPLE_OPS):
        await mailer.send(
            to=contact.email,
            subject=t(
                "dispute_sla.subject", contact.locale, overdue=overdue, due_soon=len(due) - overdue
            ),
            body=t(
                "dispute_sla.body",
                contact.locale,
                lines="\n".join(_line(dispute, now, contact.locale) for dispute in due),
            ),
        )
    return len(due)
```

In `backend/app/modules/governance/service.py`, add `from app.modules.governance.reminders import remind_due_disputes` and `"remind_due_disputes"` to `__all__`.

- [ ] **Step 6: Schedule the job**

In `backend/app/worker/jobs.py`, add `from app.core.time import utcnow` and `from app.modules.governance.service import remind_due_disputes`, then append:

```python
async def remind_dispute_sla(ctx: dict[str, Any]) -> int:
    """Daily: one digest of overdue and soon-due disputes to People Ops."""
    async with ctx["sessionmaker"]() as session:
        return await remind_due_disputes(
            session,
            ctx["mailer"],
            now=utcnow(),
            warn_days=ctx["settings"].dispute_reminder_days,
        )
```

In `backend/app/worker/settings.py`:
- add `remind_dispute_sla` to the `app.worker.jobs` import;
- in `startup`, replace the `ctx["registry"] = build_registry(...)` statement with:

```python
    mailer = build_mailer(settings)
    ctx["settings"] = settings
    ctx["mailer"] = mailer
    ctx["registry"] = build_registry(
        HandlerDeps(
            settings=settings,
            redis=handler_redis,
            mailer=mailer,
            esign=build_esign(settings),
            payroll=build_payroll(settings),
        )
    )
```

- then add `cron(remind_dispute_sla, hour={8}, minute={0}),` to `cron_jobs`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/api/governance tests/unit/test_i18n.py tests/unit/test_worker_jobs.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests/api/governance/test_dispute_sla.py
git commit -m "feat(governance): daily dispute SLA digest to People Ops

At 08:00 UTC every active People Ops account gets one digest of open
disputes that are overdue or due within three days (spec §7.7).

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 8: Identity carry-forwards

This task closes four roadmap rows:
- **Grant revocation takes a reason.** `POST /access-grants/{id}/revoke` with a required `reason` replaces `DELETE /access-grants/{id}`.
- **Logout is audited as the user.** The audit row names the user who logged out.
- **The SSO-login audit moves into the service.** `OidcLoginService.complete` writes it, instead of the router.
- **One revocation path.** A role change seen at OIDC login now runs the same revocation as SCIM:
  - sessions end;
  - the revocation marker is set;
  - open grants close;
  - `access.revoked` is audited;
  - `AccessRevoked` is emitted, which ends the user's staffing.

**Files:**
- Create: `backend/app/modules/identity/access_revocation.py`
- Modify: `backend/app/modules/identity/scim.py`, `oidc_login.py`, `router.py`, `grants.py`, `sessions.py`, `schemas.py`
- Test: `backend/tests/api/identity/test_access_grants.py`, `test_sessions.py`, `test_oidc_login.py`

**Interfaces:**
- Consumes: `RefreshSessionRepository.revoke_all_for_user`, `AccessGrantRepository.list_open_for_grantee`, `mark_revoked` (identity internals).
- Produces:
  - `identity.access_revocation.revoke_access(session, redis, settings, user, *, before, reason, marker_at) -> None`, with `RevocationReason = Literal["deactivated", "role_changed"]`.
  - `identity.schemas.GrantRevoke(reason: str 10–500)`.
  - `GrantService.revoke(actor, grant_id, reason)`.
  - Route `POST /api/v1/access-grants/{grant_id}/revoke`, returning 204. `DELETE /access-grants/{grant_id}` is removed.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/api/identity/test_access_grants.py`, add near the top:

```python
REVOKE_REASON = "The cover period ended early."
```

Replace `test_list_and_revoke` and `test_revoking_unknown_grant_is_404` with:

```python
async def test_list_and_revoke(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session)
    headers = bearer(settings, ops)
    created = await client.post(
        "/api/v1/access-grants", json=_body(pm.id, scoped_worker_id=worker.id), headers=headers
    )
    grant_id = created.json()["id"]

    listed = await client.get(
        "/api/v1/access-grants", params={"granted_to_id": str(pm.id)}, headers=headers
    )
    revoked = await client.post(
        f"/api/v1/access-grants/{grant_id}/revoke",
        json={"reason": REVOKE_REASON},
        headers=headers,
    )
    after = await client.get("/api/v1/access-grants", headers=headers)

    assert [g["id"] for g in listed.json()] == [grant_id]
    assert revoked.status_code == 204
    assert after.json() == []
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "access_grant.revoked"))
    ).one()
    assert (audit.actor_id, audit.reason) == (ops.id, REVOKE_REASON)


@pytest.mark.parametrize("body", [{}, {"reason": "too short"}])
async def test_revoking_needs_a_reason(
    client: AsyncClient, session: AsyncSession, settings: Settings, body: dict[str, str]
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session)
    headers = bearer(settings, ops)
    created = await client.post(
        "/api/v1/access-grants", json=_body(pm.id, scoped_worker_id=worker.id), headers=headers
    )

    response = await client.post(
        f"/api/v1/access-grants/{created.json()['id']}/revoke", json=body, headers=headers
    )

    assert (response.status_code, response.json()["code"]) == (422, "validation_error")


async def test_revoking_unknown_grant_is_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        f"/api/v1/access-grants/{uuid4()}/revoke",
        json={"reason": REVOKE_REASON},
        headers=bearer(settings, ops),
    )

    assert response.json()["code"] == "grant_not_found"
```

Add `pytest` and `from sqlalchemy import select` to that file's imports if they are missing.

Append to `backend/tests/api/identity/test_sessions.py`:

```python
async def test_logout_is_audited_as_the_user(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)
    issued = await _start(session, settings, user)
    _use_cookie(client, issued.refresh_token)

    await client.post("/api/v1/auth/logout")

    audit = (await session.scalars(select(AuditLog).where(AuditLog.action == "auth.logout"))).one()
    assert (audit.actor_id, audit.actor_role) == (user.id, "pm")
```

Append to `backend/tests/api/identity/test_oidc_login.py`, adding these imports to it:
- `from fakeredis import aioredis as fake_aioredis`
- `from app.modules.identity.models import AccessGrant` (next to its existing identity-models import)
- `from app.modules.identity.oidc_login import OidcLoginService`
- `make_worker` in the `tests.support` import

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/identity -v`
Expected: FAIL.
- The revoke route answers 405 (the path exists only for DELETE).
- The logout audit has `actor_id` None.
- The service-level sign-in writes no audit row.
- The role change leaves the grant open.

- [ ] **Step 3: Extract the revocation path**

`backend/app/modules/identity/access_revocation.py`:

```python
"""Ending a staff member's access (spec §7.6). SCIM and a role change seen at
OIDC login share this one path."""

from datetime import datetime
from typing import Literal

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import AccessGrantRepository, RefreshSessionRepository
from app.modules.identity.revocation import mark_revoked
from app.modules.identity.schemas import AccessRevoked

RevocationReason = Literal["deactivated", "role_changed"]

log = structlog.get_logger(__name__)


async def revoke_access(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    user: UserAccount,
    *,
    before: dict[str, str],
    reason: RevocationReason,
    marker_at: datetime,
) -> None:
    """Ends refresh sessions, marks access tokens issued before `marker_at`
    revoked, closes the user's open grants (FR-9.5), audits, and emits
    AccessRevoked, whose handler ends the user's project staffing."""
    now = utcnow()
    await RefreshSessionRepository(session).revoke_all_for_user(user.id, now, reason="admin")
    try:
        await mark_revoked(redis, settings, user.id, marker_at)
    except (RedisError, OSError):
        # The DB revocation (refresh sessions + status) is durable and commits
        # regardless; the marker only shortens the window during which an
        # already-issued access token keeps working, and the 10-min
        # access-token TTL already bounds that exposure (spec §8.1).
        log.error("auth.revocation_marker_unavailable", user_id=str(user.id))
    for grant in await AccessGrantRepository(session).list_open_for_grantee(user.id):
        grant.revoked_at = now
        await write_audit(
            session,
            actor=None,
            action="access_grant.revoked",
            target_type="access_grant",
            target_id=grant.id,
            before={"revoked_at": None},
            after={"revoked_at": grant.revoked_at.isoformat()},
            reason=reason,
        )
    await write_audit(
        session,
        actor=None,
        action="access.revoked",
        target_type="user_account",
        target_id=user.id,
        before=before,
        after={"status": user.status.value, "role": user.role.value},
        reason=reason,
    )
    await emit_event(session, AccessRevoked(aggregate_id=user.id, reason=reason))
```

In `backend/app/modules/identity/scim.py`:
- delete the `_revoke` method;
- in `patch_user`, replace `await self._revoke(user, before, reason)` with:

```python
            await revoke_access(
                self.session,
                self.redis,
                self.settings,
                user,
                before=before,
                reason=reason,
                marker_at=utcnow(),
            )
```

- add `from app.modules.identity.access_revocation import revoke_access`;
- remove `self.refresh` and `self.grants` from `__init__`, then delete the imports ruff reports as unused (`structlog`/`log`, `RedisError`, `emit_event`, `mark_revoked`, `AccessRevoked`, `RefreshSessionRepository`, `AccessGrantRepository`).

- [ ] **Step 4: Rewrite the OIDC login service**

Replace `backend/app/modules/identity/oidc_login.py` with:

```python
import json
import secrets
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.errors import BadRequest, Conflict, Forbidden
from app.core.time import utcnow
from app.modules.identity.access_revocation import revoke_access
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

    async def begin(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(48)
        await self.redis.set(
            STATE_PREFIX + state,
            json.dumps({"nonce": nonce, "code_verifier": code_verifier}),
            ex=STATE_TTL_SECONDS,
        )
        url = await self.provider.authorization_url(
            state=state, nonce=nonce, code_verifier=code_verifier
        )
        return url, state

    async def complete(self, *, code: str, state: str) -> tuple[UserAccount, IdTokenClaims]:
        raw = await self.redis.getdel(STATE_PREFIX + state)
        if raw is None:
            raise BadRequest("Sign-in session expired; start again", code="oidc_state_invalid")
        pending = json.loads(raw)
        claims = await self.provider.exchange_code(
            code=code, code_verifier=pending["code_verifier"], nonce=pending["nonce"]
        )
        self._require_mfa(claims)
        user = await self._upsert(claims, self._role_for(claims.groups))
        await write_audit(
            self.session,
            actor=Actor(user_id=user.id, role=user.role),
            action="auth.sso_login",
            target_type="user_account",
            target_id=user.id,
            after={"amr": claims.amr},
        )
        return user, claims

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
            # The same path as a SCIM role change (spec §7.6). The marker is
            # one second in the past: tokens from before this login stop
            # working, while the session this login is about to issue stays
            # valid.
            await revoke_access(
                self.session,
                self.redis,
                self.settings,
                user,
                before={"status": user.status.value, "role": previous.value},
                reason="role_changed",
                marker_at=utcnow() - timedelta(seconds=1),
            )
        return user
```

In `backend/app/modules/identity/router.py`, delete the `await write_audit(...)` block from `oidc_callback`, and remove the `write_audit` import.

- [ ] **Step 5: Revocation reason and logout actor**

Append to `backend/app/modules/identity/schemas.py`:

```python
class GrantRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=500)
```

In `backend/app/modules/identity/grants.py`, change `revoke` to take the reason and record it:

```python
    async def revoke(self, actor: Actor, grant_id: UUID, reason: str) -> None:
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
            reason=reason,
        )
```

In `backend/app/modules/identity/router.py`, add `GrantRevoke` to the schemas import and replace the `DELETE` route with:

```python
@router.post("/access-grants/{grant_id}/revoke", status_code=204)
async def revoke_access_grant(
    grant_id: UUID, body: GrantRevoke, actor: GrantManager, session: SessionDep
) -> None:
    await GrantService(session).revoke(actor, grant_id, body.reason)
```

In `backend/app/modules/identity/sessions.py`, add `from app.core.context import Actor` and replace `end` with:

```python
    async def end(self, refresh_token: str) -> None:
        current = await self.refresh.get_by_hash(hash_token(refresh_token))
        if current is None:
            return
        await self.refresh.revoke_family(current.family_id, utcnow(), reason="logout")
        user = await self.users.get(current.user_id)
        await write_audit(
            self.session,
            actor=Actor(user_id=user.id, role=user.role, worker_id=user.worker_id)
            if user is not None
            else None,
            action="auth.logout",
            target_type="user_account",
            target_id=current.user_id,
            after={"family_id": str(current.family_id)},
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/api/identity tests/integration/test_visibility_policy.py -v`
Expected: PASS. The existing SCIM and OIDC role-change tests pass unchanged.

- [ ] **Step 7: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app/modules/identity tests/api/identity
git commit -m "feat(identity): one revocation path; audited reasons and actors

A role change at OIDC login now closes grants and audits access.revoked like
SCIM does. Grant revocation takes a reason (POST /access-grants/{id}/revoke),
logout is audited as the user, and the SSO-login audit moves into the service.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 9: Passport audit carry-forwards and the roadmap

This task closes three roadmap rows:
- Consent and onboarding audit rows carry `before` values.
- A name change is audited as `worker.renamed` without the name.
- A PATCH that changes nothing emits no `WorkerUpdated`, and the event lists only the fields that changed.

It then brings the roadmap and project structure up to date.

**Files:**
- Modify: `backend/app/modules/passport/consents.py`, `profile.py`; `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`; `PROJECT_STRUCTURE.md`
- Test: `backend/tests/api/passport/test_consents.py`, `test_worker_profile.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - audit `consent.granted` / `consent.withdrawn` with `before={"purpose", "granted"}`;
  - audit `worker.onboarding_completed` with `before`/`after` `onboarding_state`;
  - audit `worker.renamed` (no before/after);
  - `WorkerUpdated.fields` lists changed fields only.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/passport/test_consents.py`:

```python
async def test_the_audit_row_records_the_previous_value(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)

    await client.put(f"{URL}/cross_region_matching", json={"granted": False}, headers=headers)

    withdrawn = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "consent.withdrawn"))
    ).one()
    assert (withdrawn.before, withdrawn.after) == (
        {"purpose": "cross_region_matching", "granted": True},
        {"purpose": "cross_region_matching", "granted": False},
    )
```

Append to `backend/tests/api/passport/test_worker_profile.py` (add `import json` to its imports):

```python
async def test_renaming_is_audited_without_the_name(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session, full_name="Kofi Mensah")

    response = await client.patch(
        "/api/v1/workers/me", json={"full_name": "Kofi A. Mensah"}, headers=bearer(settings, account)
    )

    assert response.status_code == 200
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "worker.renamed"))
    ).one()
    assert audit.target_id == worker.id
    assert "Kofi" not in json.dumps([audit.before, audit.after, audit.reason])


async def test_a_patch_that_changes_nothing_emits_no_event(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session, full_name="Kofi Mensah")

    response = await client.patch(
        "/api/v1/workers/me", json={"full_name": "Kofi Mensah"}, headers=bearer(settings, account)
    )

    assert response.status_code == 200
    assert (await session.scalars(select(OutboxEvent))).all() == []
    assert (await session.scalars(select(AuditLog))).all() == []


async def test_the_event_lists_only_fields_that_changed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session, full_name="Kofi Mensah")

    await client.patch(
        "/api/v1/workers/me",
        json={"full_name": "Kofi Mensah", "base_location": "Kumasi"},
        headers=bearer(settings, account),
    )

    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.payload["fields"] == ["base_location"]


async def test_onboarding_audit_records_the_state_change(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session, onboarding_state=OnboardingState.INVITED)
    worker.base_location = "Accra"
    worker.languages = ["en"]
    await session.commit()
    await _add_skill_claim(session, worker.id)

    response = await client.post(
        "/api/v1/workers/me/onboarding/complete", headers=bearer(settings, account)
    )

    assert response.status_code == 200
    audit = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "worker.onboarding_completed")
        )
    ).one()
    assert (audit.before, audit.after) == (
        {"onboarding_state": "invited"},
        {"onboarding_state": "profile_complete"},
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/passport -v`
Expected: FAIL. The consent `before` is None, and there is no `worker.renamed` row. The no-op PATCH emits an event, the changed-fields event lists `full_name`, and the onboarding `before` is None.

- [ ] **Step 3: Record the previous consent value**

In `backend/app/modules/passport/consents.py`, add this argument to the `write_audit(...)` call in `set`, before `after=`:

```python
            before={"purpose": purpose.value, "granted": current},
```

- [ ] **Step 4: Audit renames and emit only real changes**

In `backend/app/modules/passport/profile.py`, replace the end of `update_self`, starting at `for field, value in changes.items():`, with:

```python
        changed = sorted(
            field for field, value in changes.items() if getattr(worker, field) != value
        )
        if "full_name" in changed:
            # Spec §6.3: the audit log is append-only and outlives erasure, so
            # it records that the name changed, never the name itself.
            await write_audit(
                self.session,
                actor=who.actor,
                action="worker.renamed",
                target_type="worker",
                target_id=worker.id,
            )
        for field in changed:
            setattr(worker, field, changes[field])
        if changed:
            await emit_event(self.session, WorkerUpdated(aggregate_id=worker.id, fields=changed))
        return await self.view_self(who)
```

In `complete_onboarding`, replace the `worker.onboarding_state = …` line and the `write_audit(...)` call after it with:

```python
            previous = worker.onboarding_state
            worker.onboarding_state = OnboardingState.PROFILE_COMPLETE
            await write_audit(
                self.session,
                actor=who.actor,
                action="worker.onboarding_completed",
                target_type="worker",
                target_id=worker.id,
                before={"onboarding_state": previous.value},
                after={"onboarding_state": OnboardingState.PROFILE_COMPLETE.value},
            )
```

- [ ] **Step 5: Run the passport tests**

Run: `pytest tests/api/passport tests/api/roster -v`
Expected: PASS. If an existing test PATCHes a field to its current value and asserts that the field appears in the event, update that assertion to expect only the changed fields. That is this task's intended behavior.

- [ ] **Step 6: Update the roadmap**

In `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`:

1. In the plan table, set row 4A's status to `Implemented on \`feat/governance\``.

2. Delete these carry-forward rows (4A implemented them). Each is identified by its opening words:
   - `| 4 | Grant revocation takes no \`reason\`; …`
   - `| 4 | Consent and onboarding audit rows carry only \`after\`, no \`before\`. |`
   - `| 4 | Audit that \`full_name\` changed …`
   - `| 4 | Worker and PM notifications: …`
   - `| 4 | A role change at OIDC login ends staffing …`
   - `| 4 | An upheld dispute must set \`feedback.excluded_from_standing\` …`
   - `| 4 | Notify the worker when their standing changes …`
   - `| 4 | Standing overrides (\`POST /standing-overrides\`) …`
   - `| 4 | Add DB invariants for policies: …`

3. Change the first cell of every remaining carry-forward row whose plan is `4` to `4B`.

4. Add these carry-forward rows:

```markdown
| 4B | PMs with detail visibility cannot yet see a worker's dispute status (spec §7.1 lists "disputes status" at the detail level); only People Ops and the worker read disputes. |
| 4B | Retention must anonymize \`disputes.reason\` and \`resolution_notes\` six years after resolution (spec §6.6). |
| any | The lock-order row gains feedback: the dispute-outcome handler locks the feedback row (\`FOR UPDATE\`) before its worker (\`FOR NO KEY UPDATE\`). |
```

5. Add these deviation rows:

```markdown
| 4A | Standing overrides are \`POST /workers/{worker_id}/standing-overrides\` in the standing module, not \`POST /standing-overrides\` | Request bodies never carry \`worker_id\` (visibility guard); standing owns \`standing_changes\` and governance may not import it |
| 4A | An override holds until the rules' evaluated tier differs from the one recorded at override time | Otherwise the next feedback or the nightly run silently undoes it |
| 4A | An upheld standing-change dispute changes no data; People Ops correct the tier with an override. An upheld engagement dispute excludes that engagement's feedback | Tiers are computed deterministically from the records, and only feedback carries \`excluded_from_standing\` |
| 4A | Disputes have two statuses (open, resolved), and resolution notes are required | The notes are what the worker is told; no workflow needs an intermediate status yet |
| 4A | Access grants are revoked with \`POST /access-grants/{id}/revoke\` and a required reason, replacing \`DELETE\` | The reason must be recorded (FR-9.5, spec §8.1); DELETE bodies are unreliable through proxies |
| 4A | \`FeedbackRead\` and \`StandingChangeRead\` carry \`id\` | A worker needs the id to name the record they dispute |
| 4A | Dispute record ownership comes from lookups injected by \`app/wiring.py\` | governance imports no domain module |
```

(The backslashes above only escape the backticks for this plan; write plain backticks in the roadmap.)

- [ ] **Step 7: Update the project structure**

In `PROJECT_STRUCTURE.md`, replace the `governance/` entry with:

```
│   │   │   ├── governance/                # policies (Plan 3A); disputes, audit-log API, SLA digest (Plan 4A)
│   │   │   │   ├── enums.py, models.py, repository.py, schemas.py
│   │   │   │   ├── policies.py, disputes.py, audit.py, reminders.py, notifications.py
│   │   │   │   ├── handlers.py, router.py
│   │   │   │   └── service.py
```

In the `standing/` entry, change the file line `│   │   │   │   ├── recalculation.py, evidence.py, explanation.py` to `│   │   │   │   ├── recalculation.py, evidence.py, explanation.py, overrides.py, queries.py, notifications.py`. In the `engagements/` entry, add `notifications.py` to the line listing `payroll.py, feedback.py, stuck.py, handlers.py`. In the `identity/` entry, add a line `│   │   │   │   ├── access_revocation.py   # one revocation path for SCIM and OIDC (Plan 4A)` after the `tokens.py` line.

- [ ] **Step 8: Run the full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app/modules/passport tests/api/passport ../docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md ../PROJECT_STRUCTURE.md
git commit -m "feat(passport): audit before-values and renames; skip no-op updates

Consent and onboarding audit rows carry the previous value, a rename is
audited without the name, and WorkerUpdated lists only fields that changed.
Marks Plan 4A implemented in the roadmap.

Co-Authored-By: <model> <noreply@anthropic.com>"
```

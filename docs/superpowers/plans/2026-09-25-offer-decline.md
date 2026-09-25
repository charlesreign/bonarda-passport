# Offer Decline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A freelancer can decline an engagement offer from the app with a reason; the offering PMs are told, People Ops can see it, and a decline never affects standing or roster ranking.

**Architecture:** Every cancellation goes through one helper that records a `cancel_cause` on the engagement (it stays `cancelled`; no new status). A new `declines.py` holds the worker's decline, the rule for who may see a decline, and the erasure scrub. The outbox voids a sent envelope and mails the PMs. The SPA adds a decline form on the worker's contract card and shows declines to staffed PMs and People Ops.

**Tech Stack:** FastAPI 0.115, SQLAlchemy 2 async + asyncpg, Alembic, Postgres 16 (testcontainers in tests), pytest-asyncio; React 18 + TanStack Query + react-i18next, openapi-typescript.

**Spec:** `docs/superpowers/specs/2026-09-25-offer-decline-design.md`

## Global Constraints

- Branch `feat/offer-decline`. Backend commands run from `backend/`; frontend commands from `frontend/`.
- Backend gate before every commit: `ruff format . && ruff check . && mypy && lint-imports` plus the tests named in the task. Full `pytest` in the last task.
- `engagements` must not import `standing`, `governance` or `roster` (import-linter). Other modules are reached only through their `service.py` / `schemas.py`.
- Enum columns use `pg_enum()` from `app/core/db/types.py` (native Postgres enum storing values). Check constraints are named without prefix in models (`name="..."`); the naming convention makes them `ck_engagements_<name>`, and migrations use `op.f("ck_engagements_<name>")`.
- Async tests never use `session.expire_all()` + `session.get()`; use `await session.refresh(obj)`.
- Error responses are problem+json with a `code`: 404 `engagement_not_found`, 409 `engagement_not_declinable`, 403 `permission_denied` (from `require_permission`), 422 for validation.
- Decline reasons: `rate`, `dates`, `scope`, `availability`, `other`. Note: optional, at most 500 characters; blank becomes `null`.
- The note is never written to the audit log.
- Worker-facing UI copy: "Your reason goes to this project's managers and People Ops. Declining does not affect your standing."
- Every user-facing string exists in en and fr (backend `app/core/i18n.py`, frontend `src/locales/en.ts` and `fr.ts`).
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A worker replays the decline (double click, retry) with a different reason → 200, the first reason stands, one audit row. (Task 3)
2. The e-sign provider delivers `signed` after the worker declined → the engagement stays cancelled and an `engagement.signed_after_decline` audit row is written. (Task 2)
3. A PM with DETAIL visibility through a *different* project opens the worker → declined rows (both causes) are absent, other rows are present. (Task 5)
4. A note of only whitespace → stored as `null`; 501 characters → 422. (Task 3)
5. A PM who has left the project's staff → gets no decline mail. (Task 6)

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/modules/engagements/enums.py` (modify) | `CancelCause`, `DeclineReason`, `DECLINE_CAUSES`, `DECLINABLE_STATUSES` |
| `backend/app/modules/engagements/models.py` (modify) | New `Engagement` columns and check constraints |
| `backend/alembic/versions/0016_engagement_decline.py` (create) | Enum types, columns, audit-log backfill, constraints |
| `backend/app/modules/engagements/cancellation.py` (create) | `cancel()`: the one way an engagement becomes `cancelled` |
| `backend/app/modules/engagements/declines.py` (create) | `DeclineService`, `decline_visible_to`, `staffed_project_ids`, `scrub_decline_notes` |
| `backend/app/modules/engagements/contracts.py` (modify) | Cancellation paths use `cancel()`; signed-after-decline; `void_contract` handler |
| `backend/app/modules/engagements/schemas.py` (modify) | Events, `DeclineRequest`, `DeclineRead`, `engagement_read(show_decline=)` |
| `backend/app/modules/engagements/repository.py` (modify) | `with_decline_note()` |
| `backend/app/modules/engagements/router.py` (modify) | Decline route; decline filtering on the worker's engagement list |
| `backend/app/modules/engagements/notifications.py` (modify) | `notify_offer_declined` |
| `backend/app/modules/engagements/handlers.py` (modify) | Register void, notify and scrub handlers |
| `backend/app/modules/integrations/esign.py` (modify) | `EsignAdapter.void`, `FakeEsignAdapter.void` |
| `backend/app/modules/identity/permissions.py` (modify) | `ENGAGEMENT_DECLINE_OWN` for workers |
| `backend/app/core/i18n.py` (modify) | `offer_declined.*`, `decline_reason.*` |
| `backend/tests/support.py` (modify) | `make_engagement(cancel_cause=)` |
| `backend/tests/integration/test_engagement_decline_schema.py` (create) | Constraints and backfill |
| `backend/tests/api/engagements/test_decline.py` (create) | Endpoint, voiding, neutrality, erasure |
| `backend/tests/api/engagements/test_decline_visibility.py` (create) | Who sees declines |
| `backend/tests/api/engagements/test_decline_notifications.py` (create) | PM mail |
| `backend/tests/unit/integrations/test_fake_esign.py` (create) | Fake adapter void idempotence |
| `frontend/src/api.ts`, `src/ui.tsx`, `src/pages/Passport.tsx`, `src/pages/WorkerPanel.tsx`, `src/locales/en.ts`, `src/locales/fr.ts` (modify) | Decline UI |
| `docs/permissions.md`, `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md` (modify) | Generated matrix; roadmap row and carry-forwards |

---

### Task 1: Cancel cause and decline columns

**Files:**
- Modify: `backend/app/modules/engagements/enums.py`
- Modify: `backend/app/modules/engagements/models.py` (imports; `Engagement` columns after `created_by_id`; `__table_args__`)
- Create: `backend/alembic/versions/0016_engagement_decline.py`
- Modify: `backend/tests/support.py` (`make_engagement`)
- Modify: `backend/tests/api/engagements/test_contracts.py` (`test_cancelled_before_dispatch_is_never_sent`, the `update(Engagement)` call)
- Test: `backend/tests/integration/test_engagement_decline_schema.py`

**Interfaces:**
- Produces: `CancelCause` (`WORKER_DECLINED`, `ESIGN_DECLINED`, `WORKER_ACCOUNT_MISSING`), `DeclineReason` (`RATE`, `DATES`, `SCOPE`, `AVAILABILITY`, `OTHER`), `DECLINE_CAUSES: frozenset[CancelCause]`, `DECLINABLE_STATUSES: frozenset[EngagementStatus]` in `app.modules.engagements.enums`. `Engagement.cancel_cause: CancelCause | None`, `.declined_at: datetime | None`, `.decline_reason: DeclineReason | None`, `.decline_note: str | None`, `.void_requested_at: datetime | None`. `make_engagement(..., cancel_cause: CancelCause | None = None)`.

- [ ] **Step 1: Write the failing constraint and backfill tests**

Create `backend/tests/integration/test_engagement_decline_schema.py`:

```python
import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from alembic import command
from app.core.db.errors import violated_constraint
from app.core.time import utcnow
from app.modules.engagements.enums import (
    CancelCause,
    DeclineReason,
    EngagementPath,
    EngagementStatus,
    WorkMode,
)
from app.modules.engagements.models import Engagement
from tests.support import alembic_config, make_project, make_worker

CANCELLED = EngagementStatus.CANCELLED
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


async def _violation(session: AsyncSession, **fields: Any) -> str | None:
    """Inserts one engagement with `fields` and returns the name of the
    constraint it violated, or None if the row was accepted."""
    worker, _ = await make_worker(session)
    project = await make_project(session)
    session.add(
        Engagement(
            worker_id=worker.id,
            project_id=project.id,
            path=EngagementPath.FIRST_TIME,
            start_date=date(2026, 10, 1),
            rate=Decimal("450.00"),
            currency="GHS",
            work_mode=WorkMode.REMOTE,
            contract_terms={"scope": "Build the data pipeline", "access_notes": None},
            confirmed_at=utcnow(),
            **fields,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        return violated_constraint(exc)
    await session.rollback()
    return None


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"status": CANCELLED}, "ck_engagements_cancel_cause_when_cancelled"),
        (
            {"status": EngagementStatus.ACTIVE, "cancel_cause": CancelCause.WORKER_ACCOUNT_MISSING},
            "ck_engagements_cancel_cause_when_cancelled",
        ),
        (
            {"status": CANCELLED, "cancel_cause": CancelCause.ESIGN_DECLINED},
            "ck_engagements_declined_at_when_declined",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.WORKER_ACCOUNT_MISSING,
                "declined_at": NOW,
            },
            "ck_engagements_declined_at_when_declined",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.ESIGN_DECLINED,
                "declined_at": NOW,
                "decline_reason": DeclineReason.RATE,
            },
            "ck_engagements_reason_only_for_worker_decline",
        ),
        (
            {"status": CANCELLED, "cancel_cause": CancelCause.WORKER_DECLINED, "declined_at": NOW},
            "ck_engagements_worker_decline_has_reason",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.ESIGN_DECLINED,
                "declined_at": NOW,
                "decline_note": "Too far",
            },
            "ck_engagements_note_needs_reason",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.WORKER_DECLINED,
                "declined_at": NOW,
                "decline_reason": DeclineReason.DATES,
                "decline_note": "I start another contract that week",
            },
            None,
        ),
    ],
)
async def test_decline_columns_are_consistent_with_the_status(
    session: AsyncSession, fields: dict[str, Any], constraint: str | None
) -> None:
    assert await _violation(session, **fields) == constraint


def test_backfill_takes_the_cause_from_the_audit_trail(postgres: PostgresContainer) -> None:
    base_url: str = postgres.get_connection_url()
    url = base_url.rsplit("/", 1)[0] + "/decline_backfill"
    ids = {key: uuid4() for key in ("worker", "project", "esign", "missing", "unknown", "active")}
    declined_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    async def admin(sql: str) -> None:
        engine = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(sql))
        await engine.dispose()

    async def seed() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO workers (id, full_name, worker_type, data_region) "
                    "VALUES (:id, 'Ama Owusu', 'freelancer', 'GH')"
                ),
                {"id": ids["worker"]},
            )
            await conn.execute(
                text("INSERT INTO projects (id, name, data_region) VALUES (:id, 'Volta', 'GH')"),
                {"id": ids["project"]},
            )
            for key, status in (
                ("esign", "cancelled"),
                ("missing", "cancelled"),
                ("unknown", "cancelled"),
                ("active", "active"),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO engagements (id, worker_id, project_id, path, status, "
                        "start_date, rate, currency, work_mode, contract_terms, confirmed_at) "
                        "VALUES (:id, :worker, :project, 'first_time', :status, '2026-09-01', "
                        "450, 'GHS', 'remote', CAST(:terms AS jsonb), now())"
                    ),
                    {
                        "id": ids[key],
                        "worker": ids["worker"],
                        "project": ids["project"],
                        "status": status,
                        "terms": '{"scope": "Pipeline", "access_notes": null}',
                    },
                )
            await conn.execute(
                text(
                    "INSERT INTO audit_log (action, target_type, target_id, occurred_at) "
                    "VALUES ('engagement.contract_declined', 'engagement', :id, :at)"
                ),
                {"id": ids["esign"], "at": declined_at},
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_log (action, target_type, target_id, reason) "
                    "VALUES ('engagement.cancelled', 'engagement', :id, 'worker_account_missing')"
                ),
                {"id": ids["missing"]},
            )
        await engine.dispose()

    async def causes() -> dict[str, tuple[str | None, datetime | None]]:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT id, cancel_cause, declined_at FROM engagements"))
            ).all()
        await engine.dispose()
        by_id = {row.id: (row.cancel_cause, row.declined_at) for row in rows}
        return {key: by_id[ids[key]] for key in ("esign", "missing", "unknown", "active")}

    asyncio.run(admin("DROP DATABASE IF EXISTS decline_backfill"))
    asyncio.run(admin("CREATE DATABASE decline_backfill"))
    cfg = alembic_config(url)
    command.upgrade(cfg, "0015_concentration")
    asyncio.run(seed())

    command.upgrade(cfg, "head")

    assert asyncio.run(causes()) == {
        "esign": ("esign_declined", declined_at),
        "missing": ("worker_account_missing", None),
        "unknown": ("worker_account_missing", None),
        "active": (None, None),
    }
    asyncio.run(admin("DROP DATABASE decline_backfill"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_engagement_decline_schema.py -v`
Expected: collection error `ImportError: cannot import name 'CancelCause' from 'app.modules.engagements.enums'`.

- [ ] **Step 3: Add the enums**

Append to `backend/app/modules/engagements/enums.py`:

```python
class CancelCause(enum.StrEnum):
    """Why an engagement ended `cancelled` (offer-decline spec §3)."""

    WORKER_DECLINED = "worker_declined"  # in the app
    ESIGN_DECLINED = "esign_declined"  # at the e-sign provider
    WORKER_ACCOUNT_MISSING = "worker_account_missing"  # erased before the contract went out


class DeclineReason(enum.StrEnum):
    RATE = "rate"
    DATES = "dates"
    SCOPE = "scope"
    AVAILABILITY = "availability"
    OTHER = "other"


# Declines are recorded, never scored: no standing or roster query reads these.
DECLINE_CAUSES = frozenset({CancelCause.WORKER_DECLINED, CancelCause.ESIGN_DECLINED})

# An offer can be declined until its contract is signed.
DECLINABLE_STATUSES = frozenset(
    {EngagementStatus.PENDING_SIGNATURE, EngagementStatus.AWAITING_SIGNATURE}
)
```

- [ ] **Step 4: Add the model columns and constraints**

In `backend/app/modules/engagements/models.py`, change the enums import to:

```python
from app.modules.engagements.enums import (
    CancelCause,
    DeclineReason,
    EngagementPath,
    EngagementStatus,
    ProjectStatus,
    WorkMode,
)
```

In `class Engagement`, after the `created_by_id` column, add:

```python
    cancel_cause: Mapped[CancelCause | None] = mapped_column(pg_enum(CancelCause))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[DeclineReason | None] = mapped_column(pg_enum(DeclineReason))
    decline_note: Mapped[str | None] = mapped_column(String(500))
    void_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

At the end of `Engagement.__table_args__` (after `CheckConstraint("rate > 0", name="rate_positive"),`), add:

```python
        CheckConstraint(
            "(status = 'cancelled') = (cancel_cause IS NOT NULL)",
            name="cancel_cause_when_cancelled",
        ),
        CheckConstraint(
            "COALESCE(cancel_cause IN ('worker_declined', 'esign_declined'), false)"
            " = (declined_at IS NOT NULL)",
            name="declined_at_when_declined",
        ),
        CheckConstraint(
            "decline_reason IS NULL OR cancel_cause = 'worker_declined'",
            name="reason_only_for_worker_decline",
        ),
        CheckConstraint(
            "cancel_cause IS DISTINCT FROM 'worker_declined' OR decline_reason IS NOT NULL",
            name="worker_decline_has_reason",
        ),
        CheckConstraint(
            "decline_note IS NULL OR decline_reason IS NOT NULL", name="note_needs_reason"
        ),
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/0016_engagement_decline.py`:

```python
"""engagements: cancel cause and worker decline (offer-decline spec §3)

Revision ID: 0016_engagement_decline
Revises: 0015_concentration
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_engagement_decline"
down_revision: str | None = "0015_concentration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

_CAUSE = postgresql.ENUM(
    "worker_declined",
    "esign_declined",
    "worker_account_missing",
    name="cancelcause",
    create_type=False,
)
_REASON = postgresql.ENUM(
    "rate", "dates", "scope", "availability", "other", name="declinereason", create_type=False
)
_CHECKS = {
    "cancel_cause_when_cancelled": "(status = 'cancelled') = (cancel_cause IS NOT NULL)",
    "declined_at_when_declined": (
        "COALESCE(cancel_cause IN ('worker_declined', 'esign_declined'), false)"
        " = (declined_at IS NOT NULL)"
    ),
    "reason_only_for_worker_decline": "decline_reason IS NULL OR cancel_cause = 'worker_declined'",
    "worker_decline_has_reason": (
        "cancel_cause IS DISTINCT FROM 'worker_declined' OR decline_reason IS NOT NULL"
    ),
    "note_needs_reason": "decline_note IS NULL OR decline_reason IS NOT NULL",
}


def upgrade() -> None:
    bind = op.get_bind()
    _CAUSE.create(bind)
    _REASON.create(bind)
    op.add_column("engagements", sa.Column("cancel_cause", _CAUSE, nullable=True))
    op.add_column("engagements", sa.Column("declined_at", sa.DateTime(timezone=True)))
    op.add_column("engagements", sa.Column("decline_reason", _REASON, nullable=True))
    op.add_column("engagements", sa.Column("decline_note", sa.String(500)))
    op.add_column("engagements", sa.Column("void_requested_at", sa.DateTime(timezone=True)))

    # Until now a cancellation's cause lived only in the audit trail.
    op.execute(
        """
        UPDATE engagements e
        SET cancel_cause = 'esign_declined', declined_at = a.occurred_at
        FROM (
            SELECT target_id, max(occurred_at) AS occurred_at FROM audit_log
            WHERE target_type = 'engagement' AND action = 'engagement.contract_declined'
            GROUP BY target_id
        ) a
        WHERE e.id = a.target_id AND e.status = 'cancelled'
        """
    )
    unexplained = bind.execute(
        sa.text(
            """
            SELECT e.id FROM engagements e
            WHERE e.status = 'cancelled' AND e.cancel_cause IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM audit_log a
                WHERE a.target_type = 'engagement' AND a.target_id = e.id
                  AND a.action = 'engagement.cancelled' AND a.reason = 'worker_account_missing'
              )
            """
        )
    ).scalars()
    for engagement_id in unexplained:
        log.warning("cancelled engagement %s has no recorded cause", engagement_id)
    op.execute(
        "UPDATE engagements SET cancel_cause = 'worker_account_missing' "
        "WHERE status = 'cancelled' AND cancel_cause IS NULL"
    )

    for name, condition in _CHECKS.items():
        op.create_check_constraint(op.f(f"ck_engagements_{name}"), "engagements", condition)


def downgrade() -> None:
    for name in reversed(list(_CHECKS)):
        op.drop_constraint(op.f(f"ck_engagements_{name}"), "engagements", type_="check")
    for column in (
        "void_requested_at",
        "decline_note",
        "decline_reason",
        "declined_at",
        "cancel_cause",
    ):
        op.drop_column("engagements", column)
    op.execute("DROP TYPE declinereason")
    op.execute("DROP TYPE cancelcause")
```

- [ ] **Step 6: Give test factories a cause**

In `backend/tests/support.py`, change the enums import to include the new names:

```python
from app.modules.engagements.enums import (
    DECLINE_CAUSES,
    CancelCause,
    DeclineReason,
    EngagementPath,
    EngagementStatus,
    WorkMode,
)
```

(Keep any other names that import already brings in.) Add a `cancel_cause: CancelCause | None = None` keyword parameter to `make_engagement` after `completed_at`, and replace its body with:

```python
    if status is EngagementStatus.CANCELLED and cancel_cause is None:
        cancel_cause = CancelCause.WORKER_ACCOUNT_MISSING
    engagement = Engagement(
        worker_id=worker_id,
        project_id=project_id,
        path=path,
        status=status,
        start_date=start_date,
        end_date=end_date,
        rate=rate,
        currency=currency,
        work_mode=work_mode,
        contract_terms={"scope": scope, "access_notes": None},
        confirmed_at=utcnow(),
        completed_at=completed_at or (utcnow() if status is EngagementStatus.COMPLETED else None),
        cancel_cause=cancel_cause,
        declined_at=utcnow() if cancel_cause in DECLINE_CAUSES else None,
        decline_reason=DeclineReason.OTHER if cancel_cause is CancelCause.WORKER_DECLINED else None,
    )
    session.add(engagement)
    await session.commit()
    return engagement
```

In `backend/tests/api/engagements/test_contracts.py`, `test_cancelled_before_dispatch_is_never_sent`, change `.values(status=EngagementStatus.CANCELLED)` to:

```python
        .values(status=EngagementStatus.CANCELLED, cancel_cause=CancelCause.WORKER_DECLINED,
                declined_at=utcnow(), decline_reason=DeclineReason.OTHER)
```

and add `CancelCause, DeclineReason` to that file's `from app.modules.engagements.enums import ...` line.

- [ ] **Step 7: Run the schema tests and the migration checks**

Run: `pytest tests/integration/test_engagement_decline_schema.py tests/integration/test_migrations.py -v`
Expected: PASS (the migration tests confirm the models match the migration, the check-constraint names match, and downgrade/upgrade round-trips).

- [ ] **Step 8: Run the engagement tests that create cancelled rows**

Run: `pytest tests/api/engagements tests/api/roster -q`
Expected: PASS. A failure naming `ck_engagements_cancel_cause_when_cancelled` means some code path cancels without a cause; Task 2 routes the app's paths through `cancel()`, so only test code should hit this now — fix the test setup the way Step 6 did.

- [ ] **Step 9: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/modules/engagements/enums.py app/modules/engagements/models.py alembic/versions/0016_engagement_decline.py tests/support.py tests/api/engagements/test_contracts.py tests/integration/test_engagement_decline_schema.py
git commit -m "feat(engagements): record why an engagement was cancelled

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: One cancellation path, e-sign declines recorded

**Files:**
- Create: `backend/app/modules/engagements/cancellation.py`
- Modify: `backend/app/modules/engagements/schemas.py` (`EngagementCancelled`; new `EngagementDeclined`)
- Modify: `backend/app/modules/engagements/contracts.py` (`send_contract` account-missing branch, `ContractService._signed`, `ContractService._declined`)
- Test: `backend/tests/api/engagements/test_contracts.py`

**Interfaces:**
- Consumes: `CancelCause`, `DECLINE_CAUSES` (Task 1).
- Produces: `async def cancel(session: AsyncSession, engagement: Engagement, cause: CancelCause, *, actor: Actor | None, action: str, reason: str | None = None, after: Mapping[str, Any] | None = None) -> None` in `app.modules.engagements.cancellation`. `EngagementCancelled.cause: CancelCause`. `EngagementDeclined(aggregate_id, worker_id, project_id, cause)` with `event_type = "engagements.engagement_declined"`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/engagements/test_contracts.py` (add `from app.core.outbox.models import OutboxEvent` and `CancelCause` to the imports):

```python
async def test_esign_decline_records_the_cause_and_announces_it(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    envelope = (await _engagement(session, created["id"])).esign_envelope_id or ""

    assert await _sign(client, settings, envelope, event="declined") == 204

    engagement = await _engagement(session, created["id"])
    assert engagement.cancel_cause is CancelCause.ESIGN_DECLINED
    assert engagement.declined_at is not None
    assert engagement.decline_reason is None
    events = {
        row.event_type: row.payload
        for row in (await session.scalars(select(OutboxEvent))).all()
        if row.aggregate_id == engagement.id
    }
    assert events["engagements.engagement_cancelled"]["cause"] == "esign_declined"
    assert events["engagements.engagement_declined"]["cause"] == "esign_declined"


async def test_signed_after_a_decline_changes_nothing_but_is_audited(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    envelope = (await _engagement(session, created["id"])).esign_envelope_id or ""
    assert await _sign(client, settings, envelope, event="declined") == 204

    assert await _sign(client, settings, envelope, event="signed") == 204

    engagement = await _engagement(session, created["id"])
    assert engagement.status is EngagementStatus.CANCELLED
    assert engagement.signed_at is None
    actions = (
        await session.scalars(select(AuditLog.action).where(AuditLog.target_id == engagement.id))
    ).all()
    assert "engagement.signed_after_decline" in actions
    assert "engagement.contract_signed" not in actions
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/engagements/test_contracts.py -k "decline" -v`
Expected: FAIL — `cancel_cause` is `None` after the declined webhook (and no `engagement_declined` event exists).

- [ ] **Step 3: Add the events**

In `backend/app/modules/engagements/schemas.py`, add `CancelCause` to the `app.modules.engagements.enums` import and replace `EngagementCancelled` with:

```python
class EngagementCancelled(DomainEvent):
    event_type: ClassVar[str] = "engagements.engagement_cancelled"
    worker_id: UUID
    project_id: UUID
    cause: CancelCause


class EngagementDeclined(DomainEvent):
    """The worker said no, in the app or at the e-sign provider. Drives the PM
    mail only: nothing scores a decline (offer-decline spec §1)."""

    event_type: ClassVar[str] = "engagements.engagement_declined"
    worker_id: UUID
    project_id: UUID
    cause: CancelCause
```

- [ ] **Step 4: Write the cancellation helper**

Create `backend/app/modules/engagements/cancellation.py`:

```python
"""The one way an engagement becomes `cancelled`, so every cancellation
records its cause (and a decline its time) and emits the same events."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.enums import DECLINE_CAUSES, CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.schemas import EngagementCancelled, EngagementDeclined


async def cancel(
    session: AsyncSession,
    engagement: Engagement,
    cause: CancelCause,
    *,
    actor: Actor | None,
    action: str,
    reason: str | None = None,
    after: Mapping[str, Any] | None = None,
) -> None:
    """Callers lock the row first. A worker decline sets `decline_reason`
    (and any note) before calling, so the row is valid when it flushes."""
    declined = cause in DECLINE_CAUSES
    engagement.status = EngagementStatus.CANCELLED
    engagement.cancel_cause = cause
    engagement.stuck_flagged_at = None
    if declined:
        engagement.declined_at = utcnow()
    await write_audit(
        session,
        actor=actor,
        action=action,
        target_type="engagement",
        target_id=engagement.id,
        after=after,
        reason=reason,
    )
    await emit_event(
        session,
        EngagementCancelled(
            aggregate_id=engagement.id,
            worker_id=engagement.worker_id,
            project_id=engagement.project_id,
            cause=cause,
        ),
    )
    if declined:
        await emit_event(
            session,
            EngagementDeclined(
                aggregate_id=engagement.id,
                worker_id=engagement.worker_id,
                project_id=engagement.project_id,
                cause=cause,
            ),
        )
```

- [ ] **Step 5: Route the existing cancellations through it**

In `backend/app/modules/engagements/contracts.py`:

Add imports `from app.modules.engagements.cancellation import cancel` and `from app.modules.engagements.enums import DECLINE_CAUSES, CancelCause, EngagementStatus` (replacing the plain `EngagementStatus` import). Remove `EngagementCancelled` from the schemas import.

Replace the `if contact is None:` block in `send_contract` with:

```python
    if contact is None:
        # The worker's account is gone (erased or anonymized): nobody can sign,
        # so cancel rather than retry into the dead-letter list.
        await cancel(
            session,
            engagement,
            CancelCause.WORKER_ACCOUNT_MISSING,
            actor=None,
            action="engagement.cancelled",
            reason="worker_account_missing",
        )
        return
```

Replace the first two lines of `ContractService._signed` (`if engagement.status is not EngagementStatus.AWAITING_SIGNATURE: return  # replayed or out-of-order: nothing to do`) with:

```python
        if engagement.status is not EngagementStatus.AWAITING_SIGNATURE:
            if engagement.cancel_cause in DECLINE_CAUSES:
                # The worker declined, yet the provider reports a signature: the
                # decline stands, but People Ops should see the stray envelope.
                log.warning("engagements.signed_after_decline", engagement_id=str(engagement.id))
                await write_audit(
                    self.session,
                    actor=None,
                    action="engagement.signed_after_decline",
                    target_type="engagement",
                    target_id=engagement.id,
                )
            return  # replayed or out-of-order: nothing else to do
```

Replace the body of `ContractService._declined` with:

```python
        if engagement.status not in _SENDABLE:
            return
        await cancel(
            self.session,
            engagement,
            CancelCause.ESIGN_DECLINED,
            actor=None,
            action="engagement.contract_declined",
        )
```

- [ ] **Step 6: Run the contract tests**

Run: `pytest tests/api/engagements/test_contracts.py tests/api/roster -v`
Expected: PASS, including the two new tests and the existing account-missing test.

- [ ] **Step 7: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/modules/engagements/cancellation.py app/modules/engagements/schemas.py app/modules/engagements/contracts.py tests/api/engagements/test_contracts.py
git commit -m "feat(engagements): route every cancellation through one helper

E-sign declines now record their cause and time and emit
EngagementDeclined; a signature after a decline is audited.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The worker declines an offer

**Files:**
- Modify: `backend/app/modules/identity/permissions.py` (`Permission`, `UserRole.WORKER` set)
- Modify: `docs/permissions.md` (regenerated)
- Modify: `backend/app/modules/engagements/schemas.py` (`DeclineRequest`, `DeclineRead`, `ContractVoidRequested`, `EngagementRead.decline`, `engagement_read`)
- Create: `backend/app/modules/engagements/declines.py`
- Modify: `backend/app/modules/engagements/router.py` (new route)
- Test: `backend/tests/api/engagements/test_decline.py`

**Interfaces:**
- Consumes: `cancel()` (Task 2), `DECLINABLE_STATUSES`, `CancelCause`, `DeclineReason` (Task 1).
- Produces: `Permission.ENGAGEMENT_DECLINE_OWN = "engagement:decline_own"`. `DeclineRequest(reason: DeclineReason, note: str | None)`. `DeclineRead(cause: CancelCause, declined_at: datetime, reason: DeclineReason | None, note: str | None)`. `EngagementRead.decline: DeclineRead | None = None`. `engagement_read(engagement, feedback, *, show_decline: bool = False) -> EngagementRead`. `ContractVoidRequested(aggregate_id, envelope_id: str)` with `event_type = "engagements.contract_void_requested"`. `DeclineService(session).decline(actor: Actor, worker_id: UUID, engagement_id: UUID, data: DeclineRequest) -> Engagement` in `app.modules.engagements.declines`. Route `POST /api/v1/workers/me/engagements/{engagement_id}/decline` → 200 `EngagementRead`.

- [ ] **Step 1: Write the failing endpoint tests**

Create `backend/tests/api/engagements/test_decline.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.engagements.enums import CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.queries import standing_records
from app.modules.identity.models import UserAccount
from app.modules.integrations.service import FakeEsignAdapter
from app.modules.passport.models import Worker
from app.modules.roster.models import RosterProfile
from tests.support import (
    bearer,
    engagement_terms,
    esign_webhook,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


def _decline_url(engagement_id: object) -> str:
    return f"/api/v1/workers/me/engagements/{engagement_id}/decline"


async def _offer(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> tuple[dict[str, Any], Worker, UserAccount, UserAccount]:
    """A PM offers a first-time engagement; returns (engagement, worker,
    worker account, pm)."""
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, account = await make_ready_worker(session, email="ama@example.com")
    response = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )
    assert response.status_code == 201
    return response.json(), worker, account, pm


async def _row(session: AsyncSession, engagement_id: object) -> Engagement:
    row = await session.get(Engagement, engagement_id)
    assert row is not None
    await session.refresh(row)
    return row


async def _events(session: AsyncSession, engagement_id: object) -> list[OutboxEvent]:
    rows = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
    return [row for row in rows if str(row.aggregate_id) == str(engagement_id)]


async def test_worker_declines_before_the_contract_is_sent(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)

    response = await client.post(
        _decline_url(offer["id"]),
        json={"reason": "dates", "note": "  I start another contract that week  "},
        headers=bearer(settings, account),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["decline"]["cause"] == "worker_declined"
    assert body["decline"]["reason"] == "dates"
    assert body["decline"]["note"] == "I start another contract that week"
    await drain()
    assert esign.sent == {}
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "engagement.declined"))
    ).one()
    assert audit.actor_id == account.id
    assert audit.after == {"reason": "dates"}
    types = [e.event_type for e in await _events(session, offer["id"])]
    assert "engagements.contract_void_requested" not in types


async def test_declining_a_sent_contract_asks_to_void_the_envelope(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    await drain()
    envelope = (await _row(session, offer["id"])).esign_envelope_id

    response = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert response.status_code == 200
    void = [
        e
        for e in await _events(session, offer["id"])
        if e.event_type == "engagements.contract_void_requested"
    ]
    assert [e.payload["envelope_id"] for e in void] == [envelope]


async def test_a_replayed_decline_keeps_the_first_answer(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    first = await client.post(
        _decline_url(offer["id"]), json={"reason": "dates"}, headers=bearer(settings, account)
    )

    again = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["decline"]["reason"] == "dates"
    declined = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "engagement.declined"))
    ).all()
    assert len(declined) == 1


async def test_a_signed_offer_cannot_be_declined(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    await drain()
    envelope = (await _row(session, offer["id"])).esign_envelope_id or ""
    body, headers = esign_webhook(settings, {"envelope_id": envelope, "event": "signed"})
    assert (await client.post("/api/v1/webhooks/esign", content=body, headers=headers)).status_code == 204

    response = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert (response.status_code, response.json()["code"]) == (409, "engagement_not_declinable")


async def test_an_offer_declined_at_the_provider_cannot_be_declined_again(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_ready_worker(session)
    project = await make_project(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.ESIGN_DECLINED,
    )

    response = await client.post(
        _decline_url(engagement.id), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert (response.status_code, response.json()["code"]) == (409, "engagement_not_declinable")


async def test_only_the_offered_worker_can_decline(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    offer, _, _, pm = await _offer(client, session, settings)
    _, stranger = await make_ready_worker(session, email="kwame@example.com")

    other = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, stranger)
    )
    staff = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, pm)
    )

    assert (other.status_code, other.json()["code"]) == (404, "engagement_not_found")
    assert (staff.status_code, staff.json()["code"]) == (403, "permission_denied")
    assert (await _row(session, offer["id"])).status is EngagementStatus.PENDING_SIGNATURE


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"reason": "money"}, 422),
        ({"reason": "rate", "note": "x" * 501}, 422),
        ({"reason": "rate", "worker_id": "00000000-0000-0000-0000-000000000000"}, 422),
        ({}, 422),
    ],
)
async def test_decline_bodies_are_validated(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    payload: dict[str, object],
    status: int,
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)

    response = await client.post(
        _decline_url(offer["id"]), json=payload, headers=bearer(settings, account)
    )

    assert response.status_code == status


async def test_a_blank_note_is_stored_as_none(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)

    response = await client.post(
        _decline_url(offer["id"]),
        json={"reason": "other", "note": "   "},
        headers=bearer(settings, account),
    )

    assert response.json()["decline"]["note"] is None
    assert (await _row(session, offer["id"])).decline_note is None


async def test_a_decline_counts_toward_neither_standing_nor_the_roster(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, worker, account, _ = await _offer(client, session, settings)
    past = await make_project(session, name="Past project")
    completed = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=past.id,
        start_date=utcnow().date() - timedelta(days=60),
    )

    response = await client.post(
        _decline_url(offer["id"]), json={"reason": "scope"}, headers=bearer(settings, account)
    )
    assert response.status_code == 200
    await drain()
    await refresh_roster(session)

    # Only the completed engagement counts; the declined offer is invisible to both.
    records = await standing_records(session, worker.id)
    assert [r.engagement_id for r in records] == [completed.id]
    profile = await session.get(RosterProfile, worker.id)
    assert profile is not None
    await session.refresh(profile)
    assert profile.engagements_total == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/engagements/test_decline.py -v`
Expected: FAIL — the route returns 404 (`Not Found`, no such route).

- [ ] **Step 3: Add the permission and regenerate the matrix**

In `backend/app/modules/identity/permissions.py`, add to `Permission` after `ENGAGEMENT_READ_BILLING`:

```python
    ENGAGEMENT_DECLINE_OWN = "engagement:decline_own"  # a worker declines their own offer
```

and change the worker entry to:

```python
        UserRole.WORKER: frozenset(
            {P.WORKER_READ_SELF, P.WORKER_UPDATE_SELF, P.DISPUTE_FILE, P.ENGAGEMENT_DECLINE_OWN}
        ),
```

Run: `python -m app.modules.identity.permissions ../docs/permissions.md`
Expected: `docs/permissions.md` gains an `engagement:decline_own` row with a tick under `worker` only.

- [ ] **Step 4: Add the request, response and void event**

In `backend/app/modules/engagements/schemas.py`, extend the enums import to `CancelCause, DECLINE_CAUSES, DeclineReason` alongside the names already imported. Add after `EngagementDeclined`:

```python
class ContractVoidRequested(DomainEvent):
    """A declined offer's envelope must be withdrawn at the provider."""

    event_type: ClassVar[str] = "engagements.contract_void_requested"
    envelope_id: str


class DeclineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: DeclineReason
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DeclineRead(BaseModel):
    cause: CancelCause
    declined_at: datetime
    reason: DeclineReason | None
    note: str | None
```

Add `decline: DeclineRead | None = None` as the last field of `EngagementRead`. Change `engagement_read` to:

```python
def engagement_read(
    engagement: Engagement, feedback: Feedback | None, *, show_decline: bool = False
) -> EngagementRead:
    """`show_decline` is the caller's decision under `decline_visible_to`;
    it only adds detail to an engagement that was declined."""
    decline = None
    if (
        show_decline
        and engagement.cancel_cause in DECLINE_CAUSES
        and engagement.declined_at is not None
    ):
        decline = DeclineRead(
            cause=engagement.cancel_cause,
            declined_at=engagement.declined_at,
            reason=engagement.decline_reason,
            note=engagement.decline_note,
        )
    return EngagementRead(
```

keeping every existing keyword argument of the `EngagementRead(...)` call and adding `decline=decline,` after `feedback=...`. (`DeclineRead` must be defined above `EngagementRead` in the file, since `EngagementRead` refers to it; move the two new classes there if needed.)

- [ ] **Step 5: Write the decline service**

Create `backend/app/modules/engagements/declines.py`:

```python
"""The worker's side of an offer: declining it, and who may see a decline
afterwards (offer-decline spec §4–§5). Declines are recorded, never scored."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.engagements.cancellation import cancel
from app.modules.engagements.enums import (
    DECLINABLE_STATUSES,
    CancelCause,
    EngagementStatus,
)
from app.modules.engagements.models import Engagement
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import ContractVoidRequested, DeclineRequest


class DeclineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engagements = EngagementRepository(session)

    async def decline(
        self, actor: Actor, worker_id: UUID, engagement_id: UUID, data: DeclineRequest
    ) -> Engagement:
        # The row lock orders us against the e-sign webhook and send_contract:
        # whichever commits first wins (spec §4 Races).
        engagement = await self.engagements.get_for_update(engagement_id)
        if engagement is None or engagement.worker_id != worker_id:
            raise NotFound("Engagement not found", code="engagement_not_found")
        if engagement.cancel_cause is CancelCause.WORKER_DECLINED:
            return engagement  # a replay: the first answer stands
        if engagement.status not in DECLINABLE_STATUSES:
            raise Conflict(
                "This offer can no longer be declined", code="engagement_not_declinable"
            )
        envelope_id = (
            engagement.esign_envelope_id
            if engagement.status is EngagementStatus.AWAITING_SIGNATURE
            else None
        )
        engagement.decline_reason = data.reason
        engagement.decline_note = data.note
        await cancel(
            self.session,
            engagement,
            CancelCause.WORKER_DECLINED,
            actor=actor,
            action="engagement.declined",
            after={"reason": data.reason.value},  # never the note: erasure clears one place
        )
        if envelope_id is not None:
            await emit_event(
                self.session,
                ContractVoidRequested(aggregate_id=engagement.id, envelope_id=envelope_id),
            )
        return engagement
```

- [ ] **Step 6: Add the route**

In `backend/app/modules/engagements/router.py`: add `from app.modules.engagements.declines import DeclineService`, add `DeclineRequest` to the schemas import, add `Forbidden` to the `app.core.errors` import, and add under the other `Annotated` aliases:

```python
WorkerDecliner = Annotated[Actor, Depends(require_permission(Permission.ENGAGEMENT_DECLINE_OWN))]
```

Add after `complete_engagement`:

```python
@router.post("/workers/me/engagements/{engagement_id}/decline")
async def decline_engagement(
    engagement_id: UUID, body: DeclineRequest, actor: WorkerDecliner, session: SessionDep
) -> EngagementRead:
    """The worker declines an offer they have not signed (offer-decline spec §4)."""
    if actor.worker_id is None:
        raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
    engagement = await DeclineService(session).decline(
        actor, actor.worker_id, engagement_id, body
    )
    return engagement_read(engagement, None, show_decline=True)
```

- [ ] **Step 7: Run the tests**

Run: `pytest tests/api/engagements/test_decline.py tests/api/test_visibility_guard.py tests/unit/identity -v`
Expected: PASS. (The visibility-guard test confirms the new route takes no `worker_id` parameter or body field.)

- [ ] **Step 8: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/modules/identity/permissions.py ../docs/permissions.md app/modules/engagements/schemas.py app/modules/engagements/declines.py app/modules/engagements/router.py tests/api/engagements/test_decline.py
git commit -m "feat(engagements): let a worker decline an unsigned offer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Void the envelope of a declined offer

**Files:**
- Modify: `backend/app/modules/integrations/esign.py`
- Modify: `backend/app/modules/engagements/contracts.py` (new `void_contract`)
- Modify: `backend/app/modules/engagements/handlers.py`
- Test: `backend/tests/unit/integrations/test_fake_esign.py`, `backend/tests/api/engagements/test_decline.py`

**Interfaces:**
- Consumes: `ContractVoidRequested` (Task 3).
- Produces: `EsignAdapter.void(envelope_id: str) -> None`; `FakeEsignAdapter.voided: set[str]`; `async def void_contract(session: AsyncSession, esign: EsignAdapter, engagement_id: UUID, envelope_id: str) -> None` in `app.modules.engagements.contracts`; handler name `engagements.void_contract`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/integrations/test_fake_esign.py`:

```python
from app.modules.integrations.service import FakeEsignAdapter


async def test_voiding_twice_is_harmless() -> None:
    esign = FakeEsignAdapter()

    await esign.void("fake-env-1")
    await esign.void("fake-env-1")

    assert esign.voided == {"fake-env-1"}
```

Append to `backend/tests/api/engagements/test_decline.py` (add `from uuid import UUID`, `from sqlalchemy.ext.asyncio import async_sessionmaker` and `from app.modules.engagements.contracts import void_contract` to the imports):

```python
async def test_the_worker_process_voids_a_declined_envelope_once(
    client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    await drain()
    envelope = (await _row(session, offer["id"])).esign_envelope_id or ""
    await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    await drain()
    async with sessionmaker() as s, s.begin():  # a redelivered event
        await void_contract(s, esign, UUID(offer["id"]), envelope)

    assert esign.voided == {envelope}
    assert (await _row(session, offer["id"])).void_requested_at is not None
    voided = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "engagement.contract_voided")
        )
    ).all()
    assert len(voided) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit/integrations/test_fake_esign.py tests/api/engagements/test_decline.py -k void -v`
Expected: FAIL — `AttributeError: 'FakeEsignAdapter' object has no attribute 'void'` and `ImportError` for `void_contract`.

- [ ] **Step 3: Add `void` to the adapter**

In `backend/app/modules/integrations/esign.py`, add to `class EsignAdapter(Protocol)`:

```python
    async def void(self, envelope_id: str) -> None:
        """Withdraws a sent envelope so it can no longer be signed. Must be
        idempotent: voiding an already-voided envelope succeeds."""
        ...
```

In `FakeEsignAdapter.__init__` add `self.voided: set[str] = set()`, and add:

```python
    async def void(self, envelope_id: str) -> None:
        self.voided.add(envelope_id)
```

- [ ] **Step 4: Write the handler**

Append to `backend/app/modules/engagements/contracts.py`:

```python
async def void_contract(
    session: AsyncSession, esign: EsignAdapter, engagement_id: UUID, envelope_id: str
) -> None:
    """Outbox handler: withdraws a declined offer's envelope. A failure
    retries through the outbox, so a provider outage never blocks a decline."""
    engagement = await EngagementRepository(session).get_for_update(engagement_id)
    if engagement is None or engagement.void_requested_at is not None:
        return
    await esign.void(envelope_id)
    engagement.void_requested_at = utcnow()
    await write_audit(
        session,
        actor=None,
        action="engagement.contract_voided",
        target_type="engagement",
        target_id=engagement.id,
        after={"envelope_id": envelope_id},
    )
```

In `backend/app/modules/engagements/handlers.py`, import `void_contract` from `contracts` and `ContractVoidRequested` from `schemas`, and inside `register` add after the `send` handler registrations:

```python
    async def void(session: AsyncSession, payload: dict[str, Any]) -> None:
        await void_contract(
            session, esign, UUID(payload["aggregate_id"]), payload["envelope_id"]
        )

    registry.register(ContractVoidRequested, "engagements.void_contract", void)
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/unit/integrations tests/api/engagements/test_decline.py -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/modules/integrations/esign.py app/modules/engagements/contracts.py app/modules/engagements/handlers.py tests/unit/integrations/test_fake_esign.py tests/api/engagements/test_decline.py
git commit -m "feat(engagements): void the envelope of a declined offer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Only the right people see a decline

**Files:**
- Modify: `backend/app/modules/engagements/declines.py` (`decline_visible_to`, `staffed_project_ids`)
- Modify: `backend/app/modules/engagements/router.py` (`list_worker_engagements`)
- Test: `backend/tests/api/engagements/test_decline_visibility.py`

**Interfaces:**
- Consumes: `engagement_read(..., show_decline=)` (Task 3), `DECLINE_CAUSES` (Task 1).
- Produces: `def decline_visible_to(actor: Actor, level: Visibility, engagement: Engagement, staffed_project_ids: Collection[UUID]) -> bool`; `async def staffed_project_ids(session: AsyncSession, actor: Actor) -> set[UUID]`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/engagements/test_decline_visibility.py`:

```python
from dataclasses import dataclass
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.identity.models import UserAccount
from tests.support import bearer, make_engagement, make_project, make_ready_worker, make_user


@dataclass
class Scene:
    worker_account: UserAccount
    offering_pm: UserAccount
    other_pm: UserAccount
    people_ops: UserAccount
    admin: UserAccount
    worker_id: str
    completed: Engagement
    in_app: Engagement
    at_provider: Engagement
    account_missing: Engagement


@pytest.fixture
async def scene(session: AsyncSession) -> Scene:
    """One worker: a completed engagement on project B (so B's PM has detail
    visibility), an in-app and an e-sign decline on project A, and an
    account-missing cancellation on project B."""
    offering_pm = await make_user(session, role=UserRole.PM)
    other_pm = await make_user(session, role=UserRole.PM)
    project_a = await make_project(session, staff=[offering_pm], name="Project A")
    project_b = await make_project(session, staff=[other_pm], name="Project B")
    worker, account = await make_ready_worker(session)
    past = utcnow().date() - timedelta(days=90)
    completed = await make_engagement(
        session, worker_id=worker.id, project_id=project_b.id, start_date=past
    )
    in_app = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project_a.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.WORKER_DECLINED,
    )
    in_app.decline_note = "The dates clash with another contract"
    at_provider = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project_a.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.ESIGN_DECLINED,
    )
    account_missing = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project_b.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.WORKER_ACCOUNT_MISSING,
    )
    await session.commit()
    return Scene(
        worker_account=account,
        offering_pm=offering_pm,
        other_pm=other_pm,
        people_ops=await make_user(session, role=UserRole.PEOPLE_OPS),
        admin=await make_user(session, role=UserRole.ADMIN),
        worker_id=str(worker.id),
        completed=completed,
        in_app=in_app,
        at_provider=at_provider,
        account_missing=account_missing,
    )


async def _list(
    client: AsyncClient, settings: Settings, scene: Scene, viewer: UserAccount
) -> dict[str, dict[str, object]]:
    response = await client.get(
        f"/api/v1/workers/{scene.worker_id}/engagements", headers=bearer(settings, viewer)
    )
    assert response.status_code == 200
    return {row["id"]: row for row in response.json()}


@pytest.mark.parametrize("viewer", ["worker_account", "offering_pm", "people_ops", "admin"])
async def test_the_worker_the_offering_pm_and_people_ops_see_declines_in_full(
    client: AsyncClient, settings: Settings, scene: Scene, viewer: str
) -> None:
    rows = await _list(client, settings, scene, getattr(scene, viewer))

    in_app = rows[str(scene.in_app.id)]["decline"]
    at_provider = rows[str(scene.at_provider.id)]["decline"]
    assert isinstance(in_app, dict) and isinstance(at_provider, dict)
    assert (in_app["cause"], in_app["reason"], in_app["note"]) == (
        "worker_declined",
        "other",
        "The dates clash with another contract",
    )
    assert in_app["declined_at"] is not None
    assert (at_provider["cause"], at_provider["reason"]) == ("esign_declined", None)
    assert rows[str(scene.completed.id)]["decline"] is None


async def test_a_pm_on_another_project_never_sees_a_decline(
    client: AsyncClient, settings: Settings, scene: Scene
) -> None:
    rows = await _list(client, settings, scene, scene.other_pm)

    assert set(rows) == {str(scene.completed.id), str(scene.account_missing.id)}
    assert rows[str(scene.account_missing.id)]["decline"] is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/engagements/test_decline_visibility.py -v`
Expected: FAIL — `decline` is `None` for every viewer, and the other PM sees all four rows.

- [ ] **Step 3: Add the visibility rule**

Append to `backend/app/modules/engagements/declines.py` (add imports `from collections.abc import Collection`, `from app.core.enums import UserRole`, `from app.modules.engagements.repository import ProjectRepository` next to `EngagementRepository`, and `from app.modules.identity.service import Visibility`):

```python
_FULL_VIEWERS = frozenset({UserRole.PEOPLE_OPS, UserRole.ADMIN})


def decline_visible_to(
    actor: Actor,
    level: Visibility,
    engagement: Engagement,
    staffed_project_ids: Collection[UUID],
) -> bool:
    """The worker, People Ops, admin and the offering project's PMs see a
    decline. Nobody else learns of it, so it cannot become an informal
    penalty on the worker (offer-decline spec §5)."""
    if level is Visibility.SELF or actor.role in _FULL_VIEWERS:
        return True
    return engagement.project_id in staffed_project_ids


async def staffed_project_ids(session: AsyncSession, actor: Actor) -> set[UUID]:
    if actor.role is not UserRole.PM:
        return set()
    return {p.id for p in await ProjectRepository(session).list_staffed_by(actor.user_id)}
```

- [ ] **Step 4: Filter the worker's engagement list**

In `backend/app/modules/engagements/router.py`, import `decline_visible_to, staffed_project_ids` from `declines` and `DECLINE_CAUSES` from `enums`, and replace `list_worker_engagements` with:

```python
@router.get("/workers/{worker_id}/engagements")
async def list_worker_engagements(
    worker_id: UUID,
    actor: CurrentActor,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> list[EngagementRead]:
    repo = EngagementRepository(session)
    engagements = await repo.list_for_worker(worker_id)
    staffed = await staffed_project_ids(session, actor)
    visible = {e.id: decline_visible_to(actor, level, e, staffed) for e in engagements}
    shown = [e for e in engagements if e.cancel_cause not in DECLINE_CAUSES or visible[e.id]]
    feedback = await repo.feedback_for([e.id for e in shown])
    return [
        engagement_read(e, feedback.get(e.id), show_decline=visible[e.id]) for e in shown
    ]
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/api/engagements -v`
Expected: PASS (the existing history and staffing tests still see their rows).

- [ ] **Step 6: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/modules/engagements/declines.py app/modules/engagements/router.py tests/api/engagements/test_decline_visibility.py
git commit -m "feat(engagements): show declines only to the worker, People Ops and the offering PMs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Tell the offering PMs

**Files:**
- Modify: `backend/app/core/i18n.py`
- Modify: `backend/app/modules/engagements/notifications.py`
- Modify: `backend/app/modules/engagements/handlers.py`
- Test: `backend/tests/api/engagements/test_decline_notifications.py`

**Interfaces:**
- Consumes: `EngagementDeclined` (Task 2), `DECLINE_CAUSES`.
- Produces: `async def notify_offer_declined(session: AsyncSession, mailer: Mailer, engagement_id: UUID) -> int`; handler `engagements.notify_offer_declined`; i18n keys `offer_declined.subject`, `offer_declined.body`, `offer_declined.body.esign`, `offer_declined.no_note`, `decline_reason.<reason>`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/engagements/test_decline_notifications.py`:

```python
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement, ProjectStaff
from app.modules.engagements.notifications import notify_offer_declined
from tests.support import (
    RecordingMailer,
    bearer,
    engagement_terms,
    esign_webhook,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def test_each_staffed_pm_is_told_in_their_language(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    english = await make_user(session, role=UserRole.PM, email="efua@example.com")
    french = await make_user(session, role=UserRole.PM, email="luc@example.com", locale="fr")
    departed = await make_user(session, role=UserRole.PM, email="gone@example.com")
    project = await make_project(session, staff=[english, french, departed])
    await session.execute(  # the departed PM has left the project's staff
        update(ProjectStaff)
        .where(ProjectStaff.user_account_id == departed.id)
        .values(active_to=utcnow())
    )
    await session.commit()
    worker, account = await make_ready_worker(session, full_name="Ama Owusu")
    offer = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, english),
    )
    await client.post(
        f"/api/v1/workers/me/engagements/{offer.json()['id']}/decline",
        json={"reason": "dates", "note": "Busy that month"},
        headers=bearer(settings, account),
    )
    mailer.sent.clear()

    await drain()

    by_recipient = {m["to"]: m for m in mailer.sent}
    assert set(by_recipient) == {"efua@example.com", "luc@example.com"}
    assert by_recipient["efua@example.com"]["subject"] == (
        "Ama Owusu declined the offer on Project Volta"
    )
    assert "Reason: Dates" in by_recipient["efua@example.com"]["body"]
    assert "Busy that month" in by_recipient["efua@example.com"]["body"]
    assert by_recipient["luc@example.com"]["subject"] == (
        "Ama Owusu a refusé l'offre pour Project Volta"
    )


async def test_a_provider_decline_is_announced_without_a_reason(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    mailer: RecordingMailer,
) -> None:
    pm = await make_user(session, role=UserRole.PM, email="efua@example.com")
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session, full_name="Ama Owusu")
    offer = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )
    await drain()
    row = await session.get(Engagement, offer.json()["id"])
    assert row is not None
    await session.refresh(row)
    body, headers = esign_webhook(
        settings, {"envelope_id": row.esign_envelope_id, "event": "declined"}
    )
    await client.post("/api/v1/webhooks/esign", content=body, headers=headers)
    mailer.sent.clear()

    await drain()

    assert [m["to"] for m in mailer.sent] == ["efua@example.com"]
    assert "No reason was given" in mailer.sent[0]["body"]


async def test_nobody_to_tell_is_not_an_error(session: AsyncSession) -> None:
    worker, _ = await make_ready_worker(session)
    project = await make_project(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.WORKER_DECLINED,
    )
    mailer = RecordingMailer()

    assert await notify_offer_declined(session, mailer, engagement.id) == 0
    assert mailer.sent == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/api/engagements/test_decline_notifications.py -v`
Expected: FAIL — `ImportError: cannot import name 'notify_offer_declined'`.

- [ ] **Step 3: Add the messages**

In `backend/app/core/i18n.py`, add to the `"en"` catalog:

```python
        "offer_declined.subject": "{worker} declined the offer on {project}",
        "offer_declined.body": (
            "{worker} declined the engagement offer on {project}.\n\n"
            "Reason: {reason}\nNote: {note}\n\n"
            "The contract will not go ahead. You can offer the work to another "
            "candidate from the project's staffing page."
        ),
        "offer_declined.body.esign": (
            "{worker} declined the contract for {project} at the e-signature provider. "
            "No reason was given. You can offer the work to another candidate from the "
            "project's staffing page."
        ),
        "offer_declined.no_note": "(none)",
        "decline_reason.rate": "Rate",
        "decline_reason.dates": "Dates",
        "decline_reason.scope": "Scope of work",
        "decline_reason.availability": "Availability",
        "decline_reason.other": "Other",
```

and to the `"fr"` catalog:

```python
        "offer_declined.subject": "{worker} a refusé l'offre pour {project}",
        "offer_declined.body": (
            "{worker} a refusé l'offre d'engagement pour {project}.\n\n"
            "Motif : {reason}\nNote : {note}\n\n"
            "Le contrat n'ira pas plus loin. Vous pouvez proposer la mission à un autre "
            "candidat depuis la page de staffing du projet."
        ),
        "offer_declined.body.esign": (
            "{worker} a refusé le contrat pour {project} chez le prestataire de signature "
            "électronique. Aucun motif n'a été donné. Vous pouvez proposer la mission à un "
            "autre candidat depuis la page de staffing du projet."
        ),
        "offer_declined.no_note": "(aucune)",
        "decline_reason.rate": "Tarif",
        "decline_reason.dates": "Dates",
        "decline_reason.scope": "Périmètre",
        "decline_reason.availability": "Disponibilité",
        "decline_reason.other": "Autre",
```

- [ ] **Step 4: Write the notification**

In `backend/app/modules/engagements/notifications.py`, change the enums import to `from app.modules.engagements.enums import DECLINE_CAUSES, EngagementStatus` and append:

```python
async def notify_offer_declined(
    session: AsyncSession, mailer: Mailer, engagement_id: UUID
) -> int:
    """To every active PM staffed on the project when the worker declines, in
    the app or at the e-sign provider. Returns how many PMs were told."""
    engagement = await EngagementRepository(session).get(engagement_id)
    if engagement is None or engagement.cancel_cause not in DECLINE_CAUSES:
        return 0
    projects = ProjectRepository(session)
    project = await projects.get(engagement.project_id)
    if project is None:
        return 0
    name = await worker_name(session, engagement.worker_id) or ""
    pm_ids = await active_pm_ids(session, await projects.active_staff_ids(project.id))
    for user_id in sorted(pm_ids, key=str):
        contact = await account_contact(session, user_id)
        locale = contact.locale
        if engagement.decline_reason is None:
            body = t("offer_declined.body.esign", locale, worker=name, project=project.name)
        else:
            body = t(
                "offer_declined.body",
                locale,
                worker=name,
                project=project.name,
                reason=t(f"decline_reason.{engagement.decline_reason.value}", locale),
                note=engagement.decline_note or t("offer_declined.no_note", locale),
            )
        await mailer.send(
            to=contact.email,
            subject=t("offer_declined.subject", locale, worker=name, project=project.name),
            body=body,
        )
    return len(pm_ids)
```

In `backend/app/modules/engagements/handlers.py`, import `notify_offer_declined` and `EngagementDeclined`, and add next to the other mail handlers:

```python
    async def offer_declined(session: AsyncSession, payload: dict[str, Any]) -> None:
        await notify_offer_declined(session, mailer, UUID(payload["aggregate_id"]))

    registry.register(EngagementDeclined, "engagements.notify_offer_declined", offer_declined)
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/api/engagements/test_decline_notifications.py tests/unit/test_i18n.py tests/api/test_notifications.py -v`
Expected: PASS (the i18n parity test confirms en and fr define the same keys).

- [ ] **Step 6: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/core/i18n.py app/modules/engagements/notifications.py app/modules/engagements/handlers.py tests/api/engagements/test_decline_notifications.py
git commit -m "feat(engagements): mail the offering PMs when a worker declines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Erasure clears decline notes

**Files:**
- Modify: `backend/app/modules/engagements/repository.py` (`EngagementRepository.with_decline_note`)
- Modify: `backend/app/modules/engagements/declines.py` (`scrub_decline_notes`)
- Modify: `backend/app/modules/engagements/handlers.py`
- Test: `backend/tests/api/engagements/test_decline.py`

**Interfaces:**
- Produces: `EngagementRepository.with_decline_note(worker_id: UUID) -> list[Engagement]`; `async def scrub_decline_notes(session: AsyncSession, *, worker_id: UUID) -> int` in `declines`; handler `engagements.scrub_decline_notes` on `"passport.worker_anonymized"`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/engagements/test_decline.py`:

```python
async def test_anonymizing_the_worker_removes_the_note_but_keeps_the_reason(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, worker, account, _ = await _offer(client, session, settings)
    await client.post(
        _decline_url(offer["id"]),
        json={"reason": "dates", "note": "My daughter is due that week"},
        headers=bearer(settings, account),
    )
    people_ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        f"/api/v1/workers/{worker.id}/anonymize",
        json={"reason": "Erasure request received by email"},
        headers=bearer(settings, people_ops),
    )
    assert response.status_code == 204
    await drain()

    row = await _row(session, offer["id"])
    assert (row.decline_note, row.decline_reason) == (None, "dates")
    removed = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "engagement.decline_note_removed")
        )
    ).all()
    assert [a.target_id for a in removed] == [row.id]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/api/engagements/test_decline.py -k anonymizing -v`
Expected: FAIL — `decline_note` is still set.

- [ ] **Step 3: Add the query and the scrub**

In `backend/app/modules/engagements/repository.py`, add to `EngagementRepository`:

```python
    async def with_decline_note(self, worker_id: UUID) -> list[Engagement]:
        stmt = select(Engagement).where(
            Engagement.worker_id == worker_id, Engagement.decline_note.is_not(None)
        )
        return list((await self.session.scalars(stmt)).all())
```

Append to `backend/app/modules/engagements/declines.py` (add `from app.core.audit.writer import write_audit`):

```python
async def scrub_decline_notes(session: AsyncSession, *, worker_id: UUID) -> int:
    """Erasure (spec §6.3): the note is personal free text; the reason and
    cause are structural and stay. Returns how many notes were removed."""
    engagements = await EngagementRepository(session).with_decline_note(worker_id)
    for engagement in engagements:
        engagement.decline_note = None
        await write_audit(
            session,
            actor=None,
            action="engagement.decline_note_removed",
            target_type="engagement",
            target_id=engagement.id,
            reason="worker_anonymized",
        )
    return len(engagements)
```

In `backend/app/modules/engagements/handlers.py`, import `scrub_decline_notes` from `declines` and add after the `scrub_feedback_text` registration:

```python
    async def scrub_notes(session: AsyncSession, payload: dict[str, Any]) -> None:
        await scrub_decline_notes(session, worker_id=UUID(payload["aggregate_id"]))

    registry.register("passport.worker_anonymized", "engagements.scrub_decline_notes", scrub_notes)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/api/engagements/test_decline.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports
git add app/modules/engagements/repository.py app/modules/engagements/declines.py app/modules/engagements/handlers.py tests/api/engagements/test_decline.py
git commit -m "feat(engagements): erase decline notes when a worker is anonymized

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Decline in the web app

**Files:**
- Modify: `frontend/openapi.json`, `frontend/src/api-schema.d.ts` (regenerated)
- Modify: `frontend/src/api.ts` (type aliases)
- Modify: `frontend/src/ui.tsx` (`DeclineSummary`)
- Modify: `frontend/src/pages/Passport.tsx` (`DeclineOffer`, `ContractToSign`, `Engagements`)
- Modify: `frontend/src/pages/WorkerPanel.tsx` (`EngagementRow`, engagements section)
- Modify: `frontend/src/locales/en.ts`, `frontend/src/locales/fr.ts`

**Interfaces:**
- Consumes: `POST /workers/me/engagements/{id}/decline`, `EngagementRead.decline` (Tasks 3, 5).
- Produces: `type DeclineReason`, `type Decline` in `api.ts`; `DeclineSummary({ decline, showNote })` in `ui.tsx`.

There is no frontend test runner (Playwright is a roadmap carry-forward), so this task is verified by the type check, the build, the size budget, the API drift check and a manual run.

- [ ] **Step 1: Regenerate the API types**

Run (from `frontend/`): `npm run gen:api`
Expected: `openapi.json` gains `/api/v1/workers/me/engagements/{engagement_id}/decline`, `DeclineRequest`, `DeclineRead`, `DeclineReason`, `CancelCause`; `api-schema.d.ts` is regenerated.

- [ ] **Step 2: Add the type aliases**

In `frontend/src/api.ts`, after `export type Engagement = S["EngagementRead-Output"];` add:

```ts
export type Decline = S["DeclineRead"];
export type DeclineReason = S["DeclineReason"];
```

- [ ] **Step 3: Add the strings**

In `frontend/src/locales/en.ts`, inside `passport`, after the `contract` block, add:

```ts
    decline: {
      open: "Decline offer",
      reason: "Why are you declining?",
      pick: "Choose a reason",
      note: "Anything to add? (optional)",
      count: "{{count}}/500",
      privacy: "Your reason goes to this project's managers and People Ops. Declining does not affect your standing.",
      confirm: "Decline offer",
      sending: "Declining…",
      tooLate: "This offer can no longer be declined.",
    },
```

inside `engagement`, add:

```ts
    declined: "Declined on {{date}}",
    declinedAtProvider: "Declined at the e-signature provider on {{date}}",
    declinedOffers: "Declined offers: {{count}}",
```

and a new top-level block after `workMode`:

```ts
  declineReason: {
    rate: "Rate",
    dates: "Dates",
    scope: "Scope of work",
    availability: "Availability",
    other: "Other",
  },
```

In `frontend/src/locales/fr.ts`, in the same places:

```ts
    decline: {
      open: "Refuser l'offre",
      reason: "Pourquoi refusez-vous ?",
      pick: "Choisissez un motif",
      note: "Quelque chose à ajouter ? (facultatif)",
      count: "{{count}}/500",
      privacy: "Votre motif est transmis aux responsables de ce projet et à People Ops. Refuser n'affecte pas votre niveau.",
      confirm: "Refuser l'offre",
      sending: "Refus en cours…",
      tooLate: "Cette offre ne peut plus être refusée.",
    },
```

```ts
    declined: "Refusée le {{date}}",
    declinedAtProvider: "Refusée chez le prestataire de signature le {{date}}",
    declinedOffers: "Offres refusées : {{count}}",
```

```ts
  declineReason: {
    rate: "Tarif",
    dates: "Dates",
    scope: "Périmètre",
    availability: "Disponibilité",
    other: "Autre",
  },
```

- [ ] **Step 4: Add the shared decline summary**

In `frontend/src/ui.tsx`, add `type Decline` to the `./api` import and append:

```tsx
/** One line saying an offer was declined; the note only where the viewer may
 * read it in full (the worker, People Ops, the offering PM). */
export function DeclineSummary({ decline, showNote = true }: { decline: Decline; showNote?: boolean }) {
  const when = date(decline.declined_at);
  const line =
    decline.cause === "esign_declined"
      ? t("engagement.declinedAtProvider", { date: when })
      : t("engagement.declined", { date: when });
  return (
    <p className="muted small-text top-gap">
      {line}
      {decline.reason ? ` · ${t(`declineReason.${decline.reason}`)}` : ""}
      {showNote && decline.note ? ` · “${decline.note}”` : ""}
    </p>
  );
}
```

- [ ] **Step 5: The worker's decline form**

In `frontend/src/pages/Passport.tsx`, add `ApiError` and `type DeclineReason` to the `../api` import and `DeclineSummary` to the `../ui` import. Add above `ContractToSign`:

```tsx
const DECLINE_REASONS: DeclineReason[] = ["rate", "dates", "scope", "availability", "other"];

function DeclineOffer({ engagement }: { engagement: Engagement }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<DeclineReason | "">("");
  const [note, setNote] = useState("");
  const decline = useMutation({
    mutationFn: () =>
      api<Engagement>(`/workers/me/engagements/${engagement.id}/decline`, {
        method: "POST",
        body: { reason, note: note.trim() || null },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["engagements", engagement.worker_id] }),
  });
  const tooLate = decline.error instanceof ApiError && decline.error.code === "engagement_not_declinable";
  if (!open)
    return (
      <button className="small secondary" onClick={() => setOpen(true)}>
        <X size={16} aria-hidden="true" />
        {t("passport.decline.open")}
      </button>
    );
  return (
    <form
      className="panel-soft top-gap"
      onSubmit={(event) => {
        event.preventDefault();
        decline.mutate();
      }}
    >
      <label htmlFor={`${fieldId}-reason`}>{t("passport.decline.reason")}</label>
      <select
        id={`${fieldId}-reason`}
        required
        value={reason}
        onChange={(event) => setReason(event.target.value as DeclineReason)}
      >
        <option value="" disabled>
          {t("passport.decline.pick")}
        </option>
        {DECLINE_REASONS.map((r) => (
          <option key={r} value={r}>
            {t(`declineReason.${r}`)}
          </option>
        ))}
      </select>
      <label htmlFor={`${fieldId}-note`} className="top-gap">
        {t("passport.decline.note")}
      </label>
      <textarea
        id={`${fieldId}-note`}
        maxLength={500}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <p className="muted small-text">{t("passport.decline.count", { count: note.length })}</p>
      <InfoNote>{t("passport.decline.privacy")}</InfoNote>
      <div className="row wrap top-gap">
        <button type="submit" className="small" disabled={!reason || decline.isPending}>
          {decline.isPending ? t("passport.decline.sending") : t("passport.decline.confirm")}
        </button>
        <button type="button" className="small secondary" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </button>
      </div>
      <ErrorNote error={tooLate ? new Error(t("passport.decline.tooLate")) : decline.error} />
    </form>
  );
}
```

In `ContractToSign`, change the `pending_signature` early return to also offer the decline:

```tsx
  if (engagement.status === "pending_signature")
    return (
      <div className="top-gap">
        <p className="muted small-text row" role="status">
          <HourglassMedium size={16} aria-hidden="true" />
          {t("passport.contract.preparing")}
        </p>
        <DeclineOffer engagement={engagement} />
      </div>
    );
```

and in its final `<div className="row wrap top-gap">`, add `<DeclineOffer engagement={engagement} />` right after the sign `<button>`.

In `Engagements`, after `{IN_FLIGHT.includes(e.status) && <ContractToSign engagement={e} />}` add:

```tsx
          {e.decline && <DeclineSummary decline={e.decline} />}
```

- [ ] **Step 6: The PM and People Ops view**

In `frontend/src/pages/WorkerPanel.tsx`, add `DeclineSummary` to the `../ui` import and `import { useAuth } from "../auth";`.

In `EngagementRow`, after the `{engagement.feedback && (...)}` block, add:

```tsx
      {engagement.decline && <DeclineSummary decline={engagement.decline} />}
```

In `WorkerPanel`, after `const w = worker.data;` add:

```tsx
  const { me } = useAuth();
  const declines = engagements.data?.filter((e) => e.decline) ?? [];
  const seesDeclineCount = me?.role === "people_ops" || me?.role === "admin";
```

and inside the engagements `<section>`, right after its `<h2>`, add:

```tsx
                {seesDeclineCount && declines.length > 0 && (
                  <p className="muted small-text">{t("engagement.declinedOffers", { count: declines.length })}</p>
                )}
```

(The server already leaves declines out for PMs on other projects, so the list itself needs no filtering; the count is shown to People Ops and admin only, per the spec.)

- [ ] **Step 7: Build and check**

Run (from `frontend/`): `npm run build && npm run size && npm run check:api`
Expected: the type check and build succeed, every bundle is within budget, and `check:api` reports no diff once Step 1's regenerated files are staged.

- [ ] **Step 8: Check it by hand**

Start the demo stack (`docker compose up --build` from the repo root; see `README.md`). Then:
1. Sign in as a PM, offer a first-time engagement to a freelancer.
2. Sign in as that freelancer: on the passport, the contract card shows **Decline offer** both while "being prepared" and once ready. Decline with reason *Dates* and a note. The engagement shows "Declined on … · Dates · “…”".
3. Mailpit (see `README.md` for its URL) has one "… declined the offer on …" mail per staffed PM.
4. As the offering PM, open the freelancer from the project: the row shows the decline with note.
5. As People Ops, open the freelancer from a project: "Declined offers: 1" appears above the list.
6. Switch the language to French and repeat step 2's view: all decline strings are French.

- [ ] **Step 9: Commit**

```bash
git add openapi.json src/api-schema.d.ts src/api.ts src/ui.tsx src/pages/Passport.tsx src/pages/WorkerPanel.tsx src/locales/en.ts src/locales/fr.ts
git commit -m "feat(web): decline an offer from the passport; show declines to PMs and People Ops

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Roadmap and full verification

**Files:**
- Modify: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`

- [ ] **Step 1: Record the plan and its carry-forwards**

In the roadmap's plan table, add after the Plan 6 row:

```markdown
| — | `2026-09-25-offer-decline.md` | A worker declines an unsigned offer with a reason; PMs mailed; envelope voided; declines recorded, never scored, visible to the worker, People Ops and the offering PMs only | 5 | Implemented on `feat/offer-decline` |
```

In the carry-forward table, add:

```markdown
| any | Offer decline: a PM cannot withdraw an offer (`pm_withdrew` cause reserved, not built). |
| any | Offer decline: no organisation-wide decline rollup on the governance overview. |
| any | Offer decline: unanswered offers never lapse; an offer-expiry step would need new states and changes FR-4.3 timing. |
| any | Offer decline: decline notes are cleared on erasure only; add them to the retention cutoff alongside feedback text. |
| pre-live (real adapters) | The real e-sign adapter must implement `void` idempotently; a signature arriving after a void is audited (`engagement.signed_after_decline`) but not reversed. |
```

In the deviations table, add:

```markdown
| offer-decline | Worker-facing engagement mutation `POST /workers/me/engagements/{id}/decline` and permission `engagement:decline_own`; `engagements` gains `cancel_cause` and decline columns | The parent spec has no worker action on engagements; declining needs one |
```

- [ ] **Step 2: Run the full backend gate**

Run (from `backend/`): `ruff format --check . && ruff check . && mypy && lint-imports && pytest`
Expected: all pass. If `pytest` is killed for memory (as happened on Plan 4B), run it per directory: `pytest tests/unit`, `pytest tests/integration`, `pytest tests/api` — and report which runs completed.

- [ ] **Step 3: Commit**

```bash
git add ../docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md
git commit -m "docs(roadmap): record the offer-decline plan and its carry-forwards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

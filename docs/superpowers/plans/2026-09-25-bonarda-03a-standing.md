# Bonarda Plan 3A — Policies and Standing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned `policy_configs` with two-person activation (governance), and the `standing` module: a pure tier rules engine, append-only `standing_changes`, skill evidence with distinct-reviewer verification, re-evaluation when a tiering policy is activated, and the standing explanation API.

**Architecture:** Builds on Plans 1, 2A and 2B (branch `feat/worker-passport`). Two new modules:
- `app/modules/governance/`: policies only in this plan; disputes, concentration and overrides arrive in Plan 4.
- `app/modules/standing/`.

Tier logic lives in one pure function, `standing.rules.evaluate(records, rules, today)`, with no database access. Everything else feeds it or stores its result. Standing runs only in outbox handlers (`FeedbackSubmitted`, `PolicyActivated`) and a nightly cron, never on the request path (spec §6.5). Dependencies flow one way:
- `standing` → `governance.service`/`schemas`, `passport.service`, `engagements.service`/`schemas`.
- `governance` depends on no other domain module.

The roster (read-model, scoring, first-shot) is **Plan 3B**, written after this plan lands.

**Tech Stack:** Python 3.12, FastAPI 0.115 (pinned), Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic, Arq, pytest + Testcontainers + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`, in particular:
- §2.1 #2 (the worker sees tier, signals and policy version)
- §5.1 and §5.2 (modules and boundary rules)
- §6.1 (`policy_configs`, `skill_evidence`, `standing_changes`)
- §6.3 (append-only tables)
- §6.4 (the `standing_changes` index)
- §6.5 (tier recalculation is eventual, off the request path)
- §7.2 (governance policy routes, `GET /workers/me/standing`)
- §7.3 (the rules engine and seed tiering policy)
- §7.4 (seed matching weights, stored now and used in Plan 3B)
- §7.7 (handlers)

Roadmap with carry-forward and deviations: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`.

## Global Constraints

- **Branch and commands:**
  - Work on branch `feat/worker-passport`.
  - Run all commands from `backend/` with the venv at `backend/.venv` activated (`source .venv/Scripts/activate` in Git Bash).
  - Docker must be running (Testcontainers Postgres).
- **API conventions:** all routes are under `/api/v1`. Errors are RFC 9457 `application/problem+json` with a stable `code` field.
- **Module imports:**
  - A module imports another module only through its `service` or `schemas` submodule.
  - `app/main.py`, `app/worker/` and `app/wiring.py` are the composition root and may import anything.
  - `app.core` imports no module.
  - `governance` imports no other domain module.
  - `passport` and `engagements` never import `standing` or `governance`.
- **Audit and events:** every state change of administrative, security or fairness significance writes `write_audit(...)` on the request's (or handler's) `AsyncSession`. Every change other modules react to emits `emit_event(...)` on the same session. Audit rows about workers carry no contact data, no names and no free-text feedback.
- **Policy immutability:** policies are immutable once proposed. A change is a new version. At most one version per kind is `active`, and it was activated by someone other than its author (spec §6.1; NFR-5.1, NFR-9.2).
- **Tier logic:** tiers are computed only by `standing.rules.evaluate`. No other code decides a tier.
- **Append-only:** `standing_changes` is append-only (DB trigger, spec §6.3).
- **Integrity errors:** they are mapped by constraint name via `app.core.db.errors.violated_constraint(exc)`. Any other integrity error is re-raised, never relabelled.
- **Migrations:** enum columns use `app.core.db.types.pg_enum`. In migrations, check-constraint names go through `op.f("ck_<table>_<name>")`; unique, foreign-key, primary-key and index names are plain strings.
- **Time:** datetimes are timezone-aware UTC (`app.core.time.utcnow()`); "today" is `utcnow().date()`.
- **Async tests:** never call `session.expire_all()` followed by `session.get(...)`; use `await session.refresh(obj)`.
- **Before every commit:** from `backend/` with no path arguments, run `ruff format . && ruff check . && mypy && lint-imports && pytest`. All must pass.
- **Commit messages:** multi-line. A subject line, a blank line, then a `Co-Authored-By:` trailer naming the model that wrote the commit.

## Review Focus

1. **Self-activation is refused.** People Ops staff who proposed a policy and then try to activate it get 403 `policy_self_activation`, and the version stays `draft`. The database check `ck_policy_configs_two_person` also refuses it if the service is bypassed. (Test in Task 1.)
2. **Malformed policies are rejected at proposal.** A tier weight above 15%, matching weights not summing to 1, or tiers listed lowest-first are rejected with 422 `invalid_policy_rules` when proposed. A malformed policy can never become active. (Test in Task 1.)
3. **Concurrent recalculation is serialized.** Two recalculations of the same worker at the same moment (a feedback handler and a policy re-evaluation) produce exactly one `standing_changes` row, not two. (Test in Task 3.)
4. **A reviewer counts once per skill.** The same reviewer demonstrating a skill on two engagements counts once toward verification. With the seed threshold of 2, the skill stays unverified. (Test in Task 4.)
5. **Old or excluded feedback does not count.** Feedback outside the window, or marked `excluded_from_standing`, does not count, and a tier falls once its supporting feedback ages out, with no new event needed. (Tests in Tasks 2 and 5.)

---

## File Structure

```
backend/
  alembic/versions/0008_policies.py             policy_configs + seeded tiering/matching v1 (Task 1)
  alembic/versions/0009_standing.py             standing_changes (append-only), skill_evidence (Task 3)
  app/
    core/context.py                             + event_scope()/get_event_id() (Task 3)
    core/outbox/processing.py                   binds the event id while a handler runs (Task 3)
    models_registry.py, main.py, wiring.py      + governance, standing
    worker/jobs.py, worker/settings.py          + nightly recalculate_standing (Task 5)
    modules/governance/
      __init__.py, enums.py, models.py, repository.py, schemas.py
      policies.py                               PolicyService, active_tiering(), policy_versions()
      router.py, service.py
    modules/standing/
      __init__.py
      rules.py                                  pure evaluate() + months_before()
      models.py                                 StandingChange, SkillEvidence
      repository.py
      schemas.py                                events, explanation response
      recalculation.py                          recalculate(), recalculate_all()
      evidence.py                               record_skill_evidence(), promote_skills()
      explanation.py                            standing_explanation()
      handlers.py, router.py, service.py
    modules/passport/queries.py, service.py     + lock_standing_tier, current_standing_tier,
                                                  set_standing_tier, verify_skill, standing_worker_ids
    modules/engagements/queries.py              standing_records() (Task 2)
    modules/engagements/schemas.py, service.py  + StandingRecord
    modules/engagements/repository.py, engagements.py   has_history / reactivation carry-forward (Task 7)
  tests/support.py, tests/conftest.py           seed_policies (re-seed after TRUNCATE), make_feedback,
                                                make_engagement(completed_at=)
  tests/…                                       one file per task
docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md, PROJECT_STRUCTURE.md   (Task 8)
```

---

### Task 1: Governance policies with two-person activation

**Files:**
- Create: `backend/app/modules/governance/__init__.py`, `enums.py`, `models.py`, `repository.py`, `schemas.py`, `policies.py`, `router.py`, `service.py`; `backend/alembic/versions/0008_policies.py`
- Modify: `backend/app/models_registry.py`, `backend/app/main.py`, `backend/tests/support.py`, `backend/tests/conftest.py`
- Test: `backend/tests/api/governance/__init__.py`, `backend/tests/api/governance/test_policies.py`, `backend/tests/unit/governance/__init__.py`, `backend/tests/unit/governance/test_policy_rules.py`

**Interfaces:**
- Consumes: `write_audit`, `emit_event`, `require_permission`, `Permission.POLICY_PROPOSE`/`POLICY_ACTIVATE` (already in the matrix: people_ops only), `violated_constraint`, `UnprocessableEntity`.
- Produces:
  - Enums `PolicyKind{TIERING, MATCHING, CONCENTRATION, RETENTION}` and `PolicyStatus{DRAFT, ACTIVE, RETIRED}`.
  - Model `PolicyConfig`. Constraints: `uq_policy_configs_kind_version`, partial unique index `uq_policy_configs_active_kind`, checks `ck_policy_configs_two_person` and `ck_policy_configs_version_positive`.
  - Rule schemas in `governance.schemas`:
    - `TierRule(tier, min_completed, min_distinct_reviewers, min_positive_ratio)`
    - `SkillVerificationRule(min_distinct_reviewers)`
    - `TieringRules(window_months, tiers, default, skill_verification)`
    - `MatchingWeights`, `FirstShotRules`, `MatchingRules`
    - `RULES_BY_KIND`
  - Request/response schemas `PolicyCreate`, `PolicyRead`, `TieringPolicy(id, version, rules: TieringRules)`, and event `PolicyActivated(kind, version, previous_version)` with `event_type = "governance.policy_activated"`.
  - `PolicyService(session)`: `list_versions(kind)`, `propose(actor, kind, data)`, `activate(actor, kind, version)`.
  - Module functions `active_tiering(session) -> TieringPolicy` and `policy_versions(session, ids) -> dict[UUID, int]`. Both are exported from `governance.service` together with `PolicyKind`, `PolicyStatus`.
  - Routes:
    - `GET /api/v1/policies/{kind}/versions` (`POLICY_PROPOSE`)
    - `POST /api/v1/policies/{kind}/versions` (201; `POLICY_PROPOSE`)
    - `POST /api/v1/policies/{kind}/versions/{version}/activate` (`POLICY_ACTIVATE`)
  - Error codes:

    | Code | Status |
    |---|---|
    | `policy_kind_not_supported` | 400 |
    | `invalid_policy_rules` | 422 |
    | `policy_not_found` | 404 |
    | `policy_not_draft` | 409 |
    | `policy_self_activation` | 403 |
    | `policy_version_conflict` | 409 |
    | `policy_activation_conflict` | 409 |

  - The migration defines `SEED_POLICIES` (tiering v1, matching v1, both active, author NULL).
  - Test helper `seed_policies(conn)`. The `db_engine` fixture re-seeds after its per-test `TRUNCATE`, so every test starts with an active tiering and matching policy.

Concentration and retention policy kinds exist in the enum, but their rule schemas arrive with Plan 4. Until then, proposing one answers 400 `policy_kind_not_supported`.

- [ ] **Step 1: Enums, model, migration with seeds**

`backend/app/modules/governance/__init__.py`: empty file.

`backend/app/modules/governance/enums.py`:

```python
import enum


class PolicyKind(enum.StrEnum):
    TIERING = "tiering"
    MATCHING = "matching"
    CONCENTRATION = "concentration"  # rules schema arrives in Plan 4
    RETENTION = "retention"  # rules schema arrives in Plan 4


class PolicyStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
```

`backend/app/modules/governance/models.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.governance.enums import PolicyKind, PolicyStatus


class PolicyConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned rule set People Ops controls (NFR-5.1, NFR-9.2). Rows are
    never edited after proposal except for status transitions."""

    __tablename__ = "policy_configs"

    kind: Mapped[PolicyKind] = mapped_column(pg_enum(PolicyKind), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PolicyStatus] = mapped_column(
        pg_enum(PolicyStatus),
        default=PolicyStatus.DRAFT,
        server_default=PolicyStatus.DRAFT.value,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    activated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_policy_configs_kind_version"),
        Index(
            "uq_policy_configs_active_kind",
            "kind",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("activated_by_id <> created_by_id", name="two_person"),
        CheckConstraint("version > 0", name="version_positive"),
    )
```

`backend/alembic/versions/0008_policies.py`:

```python
"""governance: policy_configs with seeded tiering and matching v1

Revision ID: 0008_policies
Revises: 0007_engagements
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_policies"
down_revision: str | None = "0007_engagements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)

# Seed policies (spec §7.3, §7.4). Authored by the system (created_by_id NULL),
# active from the first deploy. tests/support.py re-inserts these after each
# test's TRUNCATE, so this list is the single source of truth.
SEED_POLICIES: list[dict[str, Any]] = [
    {
        "kind": "tiering",
        "version": 1,
        "notes": "Seed tiering policy (spec §7.3)",
        "rules": {
            "window_months": 24,
            "tiers": [
                {
                    "tier": "tier_2",
                    "min_completed": 3,
                    "min_distinct_reviewers": 2,
                    "min_positive_ratio": 0.8,
                },
                {
                    "tier": "tier_1",
                    "min_completed": 1,
                    "min_distinct_reviewers": 1,
                    "min_positive_ratio": 0.6,
                },
            ],
            "default": "unrated",
            "skill_verification": {"min_distinct_reviewers": 2},
        },
    },
    {
        "kind": "matching",
        "version": 1,
        "notes": "Seed matching policy (spec §7.4)",
        "rules": {
            "weights": {
                "verified_skills": 0.5,
                "self_reported_skills": 0.2,
                "availability": 0.15,
                "tier": 0.15,
            },
            "tier_weights": {"unrated": 0.0, "tier_1": 0.5, "tier_2": 1.0},
            "availability_near_days": 14,
            "first_shot": {
                "panel_size": 5,
                "underused_max_engagements_12m": 1,
                "exclude_top_candidates": 10,
            },
        },
    },
]


def upgrade() -> None:
    policy_configs = op.create_table(
        "policy_configs",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("tiering", "matching", "concentration", "retention", name="policykind"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "retired", name="policystatus"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by_id", _UUID, nullable=True),
        sa.Column("activated_by_id", _UUID, nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policy_configs"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["user_accounts.id"], name="fk_policy_configs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_id"], ["user_accounts.id"], name="fk_policy_configs_activated_by_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("kind", "version", name="uq_policy_configs_kind_version"),
        sa.CheckConstraint(
            "activated_by_id <> created_by_id", name=op.f("ck_policy_configs_two_person")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_policy_configs_version_positive")),
    )
    op.create_index(
        "uq_policy_configs_active_kind",
        "policy_configs",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        policy_configs,
        [{**seed, "status": "active", "activated_at": now} for seed in SEED_POLICIES],
    )


def downgrade() -> None:
    op.drop_index("uq_policy_configs_active_kind", table_name="policy_configs")
    op.drop_table("policy_configs")
    op.execute("DROP TYPE policystatus")
    op.execute("DROP TYPE policykind")
```

Add `from app.modules.governance import models as governance_models` to `backend/app/models_registry.py`, and add `"governance_models"` to its `__all__` in alphabetical position.

Append to `backend/tests/support.py` (imports: `importlib.util`, `from typing import Any`, `from sqlalchemy.ext.asyncio import AsyncConnection`, `from app.modules.governance.models import PolicyConfig`):

```python
def _seed_policy_rows() -> list[dict[str, Any]]:
    """The seed policies exactly as migration 0008 inserts them."""
    path = BACKEND_DIR / "alembic" / "versions" / "0008_policies.py"
    spec = importlib.util.spec_from_file_location("bonarda_migration_0008", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeds: list[dict[str, Any]] = module.SEED_POLICIES
    return seeds


async def seed_policies(conn: AsyncConnection) -> None:
    """Re-inserts the active seed policies after a test's TRUNCATE."""
    now = utcnow()
    await conn.execute(
        PolicyConfig.__table__.insert(),
        [{**seed, "status": "active", "activated_at": now} for seed in _seed_policy_rows()],
    )
```

In `backend/tests/conftest.py`, in the `db_engine` fixture's teardown, re-seed right after the `TRUNCATE`. Import `seed_policies` from `tests.support`:

```python
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await seed_policies(conn)
```

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 2: Write the failing tests**

`backend/tests/unit/governance/__init__.py` and `backend/tests/api/governance/__init__.py`: empty files.

`backend/tests/unit/governance/test_policy_rules.py`:

```python
import copy
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.governance.schemas import MatchingRules, TieringRules
from tests.support import _seed_policy_rows


def _seed(kind: str) -> dict[str, Any]:
    return copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == kind))


def test_seed_policies_are_valid() -> None:
    TieringRules.model_validate(_seed("tiering"))
    MatchingRules.model_validate(_seed("matching"))


def test_tiers_must_be_listed_highest_first() -> None:
    rules = _seed("tiering")
    rules["tiers"].reverse()

    with pytest.raises(ValidationError, match="highest first"):
        TieringRules.model_validate(rules)


def test_tiers_must_be_unique() -> None:
    rules = _seed("tiering")
    rules["tiers"][1]["tier"] = "tier_2"

    with pytest.raises(ValidationError):
        TieringRules.model_validate(rules)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["weights"].update(tier=0.2, verified_skills=0.45),  # tier above 15% (FR-3.4)
        lambda r: r["weights"].update(availability=0.2),  # sums to 1.05
        lambda r: r["tier_weights"].pop("tier_1"),
        lambda r: r["weights"].update(selection_frequency=0.0),  # FR-6.2: no such factor
        lambda r: r["first_shot"].update(panel_size=0),
    ],
)
def test_invalid_matching_rules_are_rejected(mutate: Any) -> None:
    rules = _seed("matching")
    mutate(rules)

    with pytest.raises(ValidationError):
        MatchingRules.model_validate(rules)
```

`backend/tests/api/governance/test_policies.py`:

```python
import copy
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.governance.models import PolicyConfig
from app.modules.governance.service import active_tiering
from tests.support import _seed_policy_rows, bearer, make_user


def _url(kind: str, suffix: str = "") -> str:
    return f"/api/v1/policies/{kind}/versions{suffix}"


def _tiering(**tier_2: Any) -> dict[str, Any]:
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering"))
    rules["tiers"][0].update(tier_2)
    return rules


async def _versions(session: AsyncSession, kind: str) -> dict[int, str]:
    rows = await session.execute(
        select(PolicyConfig.version, PolicyConfig.status).where(PolicyConfig.kind == kind)
    )
    return {version: status.value for version, status in rows}


async def test_people_ops_lists_the_seeded_policy(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get(_url("tiering"), headers=bearer(settings, ops))

    body = response.json()
    assert response.status_code == 200
    assert [(p["version"], p["status"]) for p in body] == [(1, "active")]
    assert body[0]["rules"]["window_months"] == 24


async def test_propose_creates_the_next_draft_version(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url("tiering"),
        json={"rules": _tiering(min_completed=4), "notes": "Stricter tier 2"},
        headers=bearer(settings, ops),
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["version"], body["status"], body["created_by_id"]) == (2, "draft", str(ops.id))
    assert await _versions(session, "tiering") == {1: "active", 2: "draft"}
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.after) == ("policy.proposed", {"kind": "tiering", "version": 2})


@pytest.mark.parametrize(
    ("kind", "rules", "status", "code"),
    [
        ("tiering", {"window_months": 24}, 422, "invalid_policy_rules"),
        ("tiering", {**_tiering(), "surprise": 1}, 422, "invalid_policy_rules"),
        ("concentration", {"threshold": 0.4}, 400, "policy_kind_not_supported"),
    ],
)
async def test_invalid_proposals_are_rejected(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    kind: str,
    rules: dict[str, Any],
    status: int,
    code: str,
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(_url(kind), json={"rules": rules}, headers=bearer(settings, ops))

    assert response.status_code == status
    assert response.json()["code"] == code
    assert await _versions(session, kind) == ({1: "active"} if kind == "tiering" else {})


async def test_the_author_cannot_activate_their_own_policy(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await client.post(_url("tiering"), json={"rules": _tiering()}, headers=bearer(settings, ops))

    response = await client.post(_url("tiering", "/2/activate"), headers=bearer(settings, ops))

    assert response.status_code == 403
    assert response.json()["code"] == "policy_self_activation"
    assert await _versions(session, "tiering") == {1: "active", 2: "draft"}


async def test_a_second_person_activates_and_the_old_version_retires(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    await client.post(
        _url("tiering"), json={"rules": _tiering()}, headers=bearer(settings, author)
    )

    response = await client.post(
        _url("tiering", "/2/activate"), headers=bearer(settings, approver)
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["activated_by_id"]) == ("active", str(approver.id))
    assert await _versions(session, "tiering") == {1: "retired", 2: "active"}
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "governance.policy_activated"
    assert (event.payload["kind"], event.payload["version"], event.payload["previous_version"]) == (
        "tiering",
        2,
        1,
    )
    activated = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "policy.activated"))
    ).one()
    assert (activated.actor_id, activated.before, activated.after) == (
        approver.id,
        {"active_version": 1},
        {"active_version": 2},
    )
    assert (await active_tiering(session)).version == 2


@pytest.mark.parametrize(("version", "status", "code"), [(1, 409, "policy_not_draft"), (9, 404, "policy_not_found")])
async def test_only_existing_drafts_can_be_activated(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    version: int,
    status: int,
    code: str,
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        _url("tiering", f"/{version}/activate"), headers=bearer(settings, ops)
    )

    assert (response.status_code, response.json()["code"]) == (status, code)


@pytest.mark.parametrize("role", [UserRole.PM, UserRole.ADMIN, UserRole.WORKER])
async def test_only_people_ops_manage_policies(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    user = await make_user(session, role=role)

    proposed = await client.post(
        _url("tiering"), json={"rules": _tiering()}, headers=bearer(settings, user)
    )

    assert proposed.status_code == 403


async def test_the_database_refuses_self_activation_too(session: AsyncSession) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    session.add(
        PolicyConfig(kind="tiering", version=2, rules=_tiering(), created_by_id=ops.id)
    )
    await session.commit()

    with pytest.raises(IntegrityError, match="ck_policy_configs_two_person"):
        await session.execute(
            update(PolicyConfig)
            .where(PolicyConfig.version == 2)
            .values(activated_by_id=ops.id)
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/governance tests/api/governance -v`
Expected: FAIL: `ModuleNotFoundError: No module named 'app.modules.governance.schemas'`.

- [ ] **Step 4: Implement**

`backend/app/modules/governance/schemas.py`:

```python
from datetime import datetime
from typing import Any, ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.outbox.events import DomainEvent
from app.modules.governance.enums import PolicyKind, PolicyStatus

# Tier names are strings here so governance stays independent of passport;
# they match passport's StandingTier values.
TierName = Literal["tier_1", "tier_2"]
_TIER_RANK = {"tier_1": 1, "tier_2": 2}


class TierRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: TierName
    min_completed: int = Field(ge=0, le=1000)
    min_distinct_reviewers: int = Field(ge=0, le=1000)
    min_positive_ratio: float = Field(ge=0, le=1)


class SkillVerificationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_distinct_reviewers: int = Field(ge=1, le=20)


class TieringRules(BaseModel):
    """Spec §7.3. The engine awards the first tier whose thresholds are all met,
    so tiers must be listed highest first."""

    model_config = ConfigDict(extra="forbid")

    window_months: int = Field(ge=1, le=120)
    tiers: list[TierRule] = Field(min_length=1, max_length=5)
    default: Literal["unrated"]
    skill_verification: SkillVerificationRule

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        ranks = [_TIER_RANK[t.tier] for t in self.tiers]
        if len(set(ranks)) != len(ranks):
            raise ValueError("each tier may appear once")
        if ranks != sorted(ranks, reverse=True):
            raise ValueError("tiers must be listed highest first")
        return self


class MatchingWeights(BaseModel):
    """Spec §7.4. Selection frequency and engagement count have no field: they
    cannot be weighted (FR-6.2)."""

    model_config = ConfigDict(extra="forbid")

    verified_skills: float = Field(ge=0, le=1)
    self_reported_skills: float = Field(ge=0, le=1)
    availability: float = Field(ge=0, le=1)
    tier: float = Field(ge=0, le=0.15)  # FR-3.4: tier is capped at 15% of the score

    @model_validator(mode="after")
    def _sums_to_one(self) -> Self:
        total = self.verified_skills + self.self_reported_skills + self.availability + self.tier
        if abs(total - 1) > 1e-6:
            raise ValueError("weights must sum to 1")
        return self


class FirstShotRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_size: int = Field(ge=1, le=20)
    underused_max_engagements_12m: int = Field(ge=0, le=50)
    exclude_top_candidates: int = Field(ge=0, le=100)


class MatchingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: MatchingWeights
    tier_weights: dict[Literal["unrated", "tier_1", "tier_2"], float]
    availability_near_days: int = Field(ge=0, le=90)
    first_shot: FirstShotRules

    @model_validator(mode="after")
    def _all_tiers_weighted(self) -> Self:
        if set(self.tier_weights) != {"unrated", "tier_1", "tier_2"}:
            raise ValueError("tier_weights must give a weight for unrated, tier_1 and tier_2")
        if any(not 0 <= w <= 1 for w in self.tier_weights.values()):
            raise ValueError("tier_weights must be between 0 and 1")
        return self


RULES_BY_KIND: dict[PolicyKind, type[BaseModel]] = {
    PolicyKind.TIERING: TieringRules,
    PolicyKind.MATCHING: MatchingRules,
}


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, Any]
    notes: str | None = Field(default=None, max_length=500)


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: PolicyKind
    version: int
    status: PolicyStatus
    rules: dict[str, Any]
    notes: str | None
    created_by_id: UUID | None
    activated_by_id: UUID | None
    activated_at: datetime | None
    created_at: datetime


class TieringPolicy(BaseModel):
    id: UUID
    version: int
    rules: TieringRules


class PolicyActivated(DomainEvent):
    """aggregate_id is the policy_configs row."""

    event_type: ClassVar[str] = "governance.policy_activated"
    kind: PolicyKind
    version: int
    previous_version: int | None
```

`backend/app/modules/governance/repository.py`:

```python
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.models import PolicyConfig


class PolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, policy: PolicyConfig) -> PolicyConfig:
        self.session.add(policy)
        return policy

    async def list_for_kind(self, kind: PolicyKind) -> list[PolicyConfig]:
        stmt = (
            select(PolicyConfig)
            .where(PolicyConfig.kind == kind)
            .order_by(PolicyConfig.version.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_for_update(self, kind: PolicyKind, version: int) -> PolicyConfig | None:
        return await self.session.scalar(
            select(PolicyConfig)
            .where(PolicyConfig.kind == kind, PolicyConfig.version == version)
            .with_for_update()
        )

    async def active(self, kind: PolicyKind, *, for_update: bool = False) -> PolicyConfig | None:
        stmt = select(PolicyConfig).where(
            PolicyConfig.kind == kind, PolicyConfig.status == PolicyStatus.ACTIVE
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def next_version(self, kind: PolicyKind) -> int:
        current = await self.session.scalar(
            select(func.max(PolicyConfig.version)).where(PolicyConfig.kind == kind)
        )
        return (current or 0) + 1

    async def versions_by_id(self, ids: Sequence[UUID]) -> dict[UUID, int]:
        if not ids:
            return {}
        rows = await self.session.execute(
            select(PolicyConfig.id, PolicyConfig.version).where(PolicyConfig.id.in_(ids))
        )
        return {policy_id: version for policy_id, version in rows}
```

`backend/app/modules/governance/policies.py`:

```python
from collections.abc import Sequence
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound, UnprocessableEntity
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.models import PolicyConfig
from app.modules.governance.repository import PolicyRepository
from app.modules.governance.schemas import (
    RULES_BY_KIND,
    PolicyActivated,
    PolicyCreate,
    PolicyRead,
    TieringPolicy,
    TieringRules,
)


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}" if location else str(error["msg"])


class PolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policies = PolicyRepository(session)

    async def list_versions(self, kind: PolicyKind) -> list[PolicyRead]:
        return [PolicyRead.model_validate(p) for p in await self.policies.list_for_kind(kind)]

    async def propose(self, actor: Actor, kind: PolicyKind, data: PolicyCreate) -> PolicyConfig:
        schema = RULES_BY_KIND.get(kind)
        if schema is None:
            raise BadRequest(
                "Policies of this kind arrive in a later release",
                code="policy_kind_not_supported",
            )
        try:
            rules = schema.model_validate(data.rules)
        except ValidationError as exc:
            raise UnprocessableEntity(_first_error(exc), code="invalid_policy_rules") from exc
        try:
            async with self.session.begin_nested():
                policy = self.policies.add(
                    PolicyConfig(
                        kind=kind,
                        version=await self.policies.next_version(kind),
                        rules=rules.model_dump(mode="json"),
                        notes=data.notes,
                        created_by_id=actor.user_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_policy_configs_kind_version":
                raise
            raise Conflict(
                "Another version was proposed at the same time; try again",
                code="policy_version_conflict",
            ) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="policy.proposed",
            target_type="policy",
            target_id=policy.id,
            after={"kind": kind.value, "version": policy.version},
        )
        return policy

    async def activate(self, actor: Actor, kind: PolicyKind, version: int) -> PolicyConfig:
        policy = await self.policies.get_for_update(kind, version)
        if policy is None:
            raise NotFound("Policy version not found", code="policy_not_found")
        if policy.status is not PolicyStatus.DRAFT:
            raise Conflict("Only a draft policy can be activated", code="policy_not_draft")
        if policy.created_by_id == actor.user_id:
            raise Forbidden(
                "A policy must be activated by someone other than its author",
                code="policy_self_activation",
            )
        current = await self.policies.active(kind, for_update=True)
        previous_version = current.version if current is not None else None
        try:
            async with self.session.begin_nested():
                if current is not None:
                    current.status = PolicyStatus.RETIRED
                    await self.session.flush()
                policy.status = PolicyStatus.ACTIVE
                policy.activated_by_id = actor.user_id
                policy.activated_at = utcnow()
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_policy_configs_active_kind":
                raise
            raise Conflict(
                "Another version was activated at the same time; reload and try again",
                code="policy_activation_conflict",
            ) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="policy.activated",
            target_type="policy",
            target_id=policy.id,
            before={"active_version": previous_version},
            after={"active_version": policy.version},
        )
        await emit_event(
            self.session,
            PolicyActivated(
                aggregate_id=policy.id,
                kind=kind,
                version=policy.version,
                previous_version=previous_version,
            ),
        )
        return policy


async def active_tiering(session: AsyncSession) -> TieringPolicy:
    policy = await PolicyRepository(session).active(PolicyKind.TIERING)
    if policy is None:
        raise RuntimeError("no active tiering policy; migration 0008 seeds one")
    return TieringPolicy(
        id=policy.id, version=policy.version, rules=TieringRules.model_validate(policy.rules)
    )


async def policy_versions(session: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, int]:
    return await PolicyRepository(session).versions_by_id(ids)
```

`backend/app/modules/governance/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.governance.enums import PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.schemas import PolicyCreate, PolicyRead
from app.modules.identity.service import Permission, require_permission

router = APIRouter(prefix="/api/v1", tags=["governance"])

PolicyProposer = Annotated[Actor, Depends(require_permission(Permission.POLICY_PROPOSE))]
PolicyActivator = Annotated[Actor, Depends(require_permission(Permission.POLICY_ACTIVATE))]


@router.get("/policies/{kind}/versions")
async def list_policy_versions(
    kind: PolicyKind, actor: PolicyProposer, session: SessionDep
) -> list[PolicyRead]:
    return await PolicyService(session).list_versions(kind)


@router.post("/policies/{kind}/versions", status_code=201)
async def propose_policy(
    kind: PolicyKind, body: PolicyCreate, actor: PolicyProposer, session: SessionDep
) -> PolicyRead:
    return PolicyRead.model_validate(await PolicyService(session).propose(actor, kind, body))


@router.post("/policies/{kind}/versions/{version}/activate")
async def activate_policy(
    kind: PolicyKind, version: int, actor: PolicyActivator, session: SessionDep
) -> PolicyRead:
    return PolicyRead.model_validate(await PolicyService(session).activate(actor, kind, version))
```

`backend/app/modules/governance/service.py`:

```python
"""Public interface of the governance module."""

from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.policies import active_tiering, policy_versions

__all__ = ["PolicyKind", "PolicyStatus", "active_tiering", "policy_versions"]
```

In `backend/app/main.py`, import `from app.modules.governance.router import router as governance_router` and add `app.include_router(governance_router)` after the engagements router.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/governance tests/api/governance tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 6: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(governance): versioned policies with two-person activation" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 2: The standing rules engine

**Files:**
- Create: `backend/app/modules/standing/__init__.py`, `backend/app/modules/standing/rules.py`, `backend/app/modules/engagements/queries.py`
- Modify: `backend/app/modules/engagements/schemas.py`, `backend/app/modules/engagements/service.py`, `backend/tests/support.py`
- Test: `backend/tests/unit/standing/__init__.py`, `backend/tests/unit/standing/test_rules.py`, `backend/tests/integration/test_standing_records.py`

**Interfaces:**
- Consumes: `TieringRules` (Task 1).
- Produces:
  - `engagements.schemas.StandingRecord(engagement_id, completed_on: date, reviewer_id: UUID | None, answers: dict[str, bool] | None, excluded: bool)`.
  - `engagements.queries.standing_records(session, worker_id) -> list[StandingRecord]`, which returns completed engagements only, with their feedback if any. It is exported from `engagements.service`.
  - In `standing.rules`:
    - `months_before(day, months) -> date`
    - `Evaluation(tier: str, completed: int, distinct_reviewers: int, positive_ratio: float, window_start: date)` with `.factors() -> dict[str, Any]`
    - `evaluate(records, rules, today) -> Evaluation`
  - Test helpers:
    - `make_engagement(..., completed_at=None)`: a COMPLETED engagement defaults to `completed_at=utcnow()`.
    - `POSITIVE_ANSWERS`
    - `make_feedback(session, *, engagement_id, reviewer_id, answers=None, skill_ids=None, excluded=False) -> Feedback`

The rules (spec §7.3):
- Records count when they are not excluded and were completed on or after `today − window_months`.
- `completed` is the number of counted records.
- Reviewers are the distinct non-null `reviewer_id`s among counted records that have feedback.
- `positive_ratio` is the share of `true` answers across all structured answers in counted feedback. It is 0 when there is no feedback.
- The tier is the first entry in `rules.tiers` (listed highest first) whose three thresholds are all met; otherwise it is `rules.default`.
- The comparison uses the unrounded ratio. `factors()` reports it rounded to 4 decimals.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/standing/__init__.py`: empty file.

`backend/tests/unit/standing/test_rules.py`:

```python
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.engagements.schemas import StandingRecord
from app.modules.governance.schemas import TieringRules
from app.modules.standing.rules import evaluate, months_before
from tests.support import _seed_policy_rows

TODAY = date(2026, 9, 25)
RULES = TieringRules.model_validate(
    next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering")
)
ALL_TRUE = {"a": True, "b": True, "c": True}


def _record(
    reviewer: UUID | None = None,
    answers: dict[str, bool] | None = None,
    *,
    days_ago: int = 30,
    excluded: bool = False,
) -> StandingRecord:
    return StandingRecord(
        engagement_id=uuid4(),
        completed_on=TODAY - timedelta(days=days_ago),
        reviewer_id=reviewer,
        answers=answers,
        excluded=excluded,
    )


def test_no_history_is_unrated() -> None:
    result = evaluate([], RULES, TODAY)

    assert (result.tier, result.completed, result.distinct_reviewers, result.positive_ratio) == (
        "unrated",
        0,
        0,
        0.0,
    )


def test_a_completed_engagement_without_feedback_is_not_enough_for_tier_1() -> None:
    assert evaluate([_record()], RULES, TODAY).tier == "unrated"


def test_one_positive_review_reaches_tier_1() -> None:
    assert evaluate([_record(uuid4(), ALL_TRUE)], RULES, TODAY).tier == "tier_1"


def test_three_engagements_two_reviewers_and_80_percent_reach_tier_2() -> None:
    ama, kwame = uuid4(), uuid4()
    mostly = {"a": True, "b": False, "c": False}  # 7 of 9 true overall = 0.78
    records = [_record(ama, ALL_TRUE), _record(kwame, ALL_TRUE), _record(ama, mostly)]

    result = evaluate(records, RULES, TODAY)

    assert (result.tier, result.distinct_reviewers) == ("tier_1", 2)
    assert result.positive_ratio == pytest.approx(0.7778, abs=1e-4)
    assert evaluate([*records[:2], _record(ama, ALL_TRUE)], RULES, TODAY).tier == "tier_2"


def test_one_reviewer_cannot_reach_tier_2_alone() -> None:
    ama = uuid4()
    records = [_record(ama, ALL_TRUE) for _ in range(5)]

    assert evaluate(records, RULES, TODAY).tier == "tier_1"


def test_excluded_and_out_of_window_records_do_not_count() -> None:
    old = _record(uuid4(), ALL_TRUE, days_ago=24 * 31 + 5)
    excluded = _record(uuid4(), ALL_TRUE, excluded=True)

    result = evaluate([old, excluded], RULES, TODAY)

    assert (result.tier, result.completed) == ("unrated", 0)


def test_the_window_start_is_inclusive() -> None:
    boundary = StandingRecord(
        engagement_id=uuid4(),
        completed_on=months_before(TODAY, 24),
        reviewer_id=uuid4(),
        answers=ALL_TRUE,
        excluded=False,
    )

    assert evaluate([boundary], RULES, TODAY).tier == "tier_1"


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2026, 3, 31), 1, date(2026, 2, 28)),
        (date(2028, 3, 31), 1, date(2028, 2, 29)),
        (date(2026, 1, 15), 24, date(2024, 1, 15)),
        (date(2026, 1, 15), 13, date(2024, 12, 15)),
    ],
)
def test_months_before(day: date, months: int, expected: date) -> None:
    assert months_before(day, months) == expected


def test_factors_report_the_inputs() -> None:
    result = evaluate([_record(uuid4(), ALL_TRUE)], RULES, TODAY)

    assert result.factors() == {
        "completed": 1,
        "distinct_reviewers": 1,
        "positive_ratio": 1.0,
        "window_start": "2024-09-25",
    }
```

Append to `backend/tests/support.py` (imports: `Feedback` from `app.modules.engagements.models`):

```python
POSITIVE_ANSWERS = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": True,
    "would_reengage": True,
}


async def make_feedback(
    session: AsyncSession,
    *,
    engagement_id: UUID,
    reviewer_id: UUID | None,
    answers: dict[str, bool] | None = None,
    skill_ids: list[UUID] | None = None,
    excluded: bool = False,
) -> Feedback:
    feedback = Feedback(
        engagement_id=engagement_id,
        reviewer_id=reviewer_id,
        structured_answers=dict(answers or POSITIVE_ANSWERS),
        skill_ids_demonstrated=skill_ids or [],
        excluded_from_standing=excluded,
    )
    session.add(feedback)
    await session.commit()
    return feedback
```

In `make_engagement` in `backend/tests/support.py`, add a keyword parameter `completed_at: datetime | None = None` and pass this to `Engagement(...)`:

```python
        completed_at=completed_at
        or (utcnow() if status is EngagementStatus.COMPLETED else None),
```

`backend/tests/integration/test_standing_records.py`:

```python
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.service import standing_records
from tests.support import make_engagement, make_feedback, make_project, make_user, make_worker


async def test_standing_records_are_completed_engagements_with_their_feedback(
    session: AsyncSession,
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session)
    project = await make_project(session)
    reviewed = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=reviewed.id, reviewer_id=pm.id, excluded=True)
    unreviewed = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        completed_at=utcnow() - timedelta(days=40),
    )
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.ACTIVE
    )

    records = {r.engagement_id: r for r in await standing_records(session, worker.id)}

    assert set(records) == {reviewed.id, unreviewed.id}
    assert records[reviewed.id].reviewer_id == pm.id
    assert records[reviewed.id].excluded is True
    assert records[reviewed.id].answers is not None
    assert records[unreviewed.id].answers is None
    assert records[unreviewed.id].excluded is False
    assert records[unreviewed.id].completed_on == (utcnow() - timedelta(days=40)).date()


async def test_completion_date_falls_back_to_end_then_start_date(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    project = await make_project(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, end_date=date(2026, 2, 1)
    )
    engagement.completed_at = None
    await session.commit()

    (record,) = await standing_records(session, worker.id)

    assert record.completed_on == date(2026, 2, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/standing tests/integration/test_standing_records.py -v`
Expected: FAIL. `ImportError: cannot import name 'StandingRecord'`.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/engagements/schemas.py`:

```python
class StandingRecord(BaseModel):
    """One completed engagement as the standing engine sees it (spec §7.3)."""

    model_config = ConfigDict(frozen=True)

    engagement_id: UUID
    completed_on: date
    reviewer_id: UUID | None
    answers: dict[str, bool] | None
    excluded: bool
```

`backend/app/modules/engagements/queries.py`:

```python
"""Read functions other modules use through engagements.service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.schemas import StandingRecord


async def standing_records(session: AsyncSession, worker_id: UUID) -> list[StandingRecord]:
    """Completed engagements with their feedback, if any, for the standing engine."""
    stmt = (
        select(
            Engagement.id,
            Engagement.completed_at,
            Engagement.end_date,
            Engagement.start_date,
            Feedback.reviewer_id,
            Feedback.structured_answers,
            Feedback.excluded_from_standing,
        )
        .outerjoin(Feedback, Feedback.engagement_id == Engagement.id)
        .where(Engagement.worker_id == worker_id, Engagement.status == EngagementStatus.COMPLETED)
    )
    return [
        StandingRecord(
            engagement_id=row.id,
            completed_on=row.completed_at.date()
            if row.completed_at is not None
            else (row.end_date or row.start_date),
            reviewer_id=row.reviewer_id,
            answers=row.structured_answers,
            excluded=bool(row.excluded_from_standing),
        )
        for row in await session.execute(stmt)
    ]
```

Export `standing_records` from `backend/app/modules/engagements/service.py`.

`backend/app/modules/standing/__init__.py`: empty file.

`backend/app/modules/standing/rules.py`:

```python
"""The tier rules engine (spec §7.3): a pure function. No database, no clock."""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.engagements.schemas import StandingRecord
from app.modules.governance.schemas import TieringRules


def months_before(day: date, months: int) -> date:
    """The same calendar day `months` earlier, clamped to the month's last day."""
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True, slots=True)
class Evaluation:
    tier: str
    completed: int
    distinct_reviewers: int
    positive_ratio: float
    window_start: date

    def factors(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "distinct_reviewers": self.distinct_reviewers,
            "positive_ratio": round(self.positive_ratio, 4),
            "window_start": self.window_start.isoformat(),
        }


def evaluate(records: Iterable[StandingRecord], rules: TieringRules, today: date) -> Evaluation:
    window_start = months_before(today, rules.window_months)
    counted = [r for r in records if not r.excluded and r.completed_on >= window_start]
    reviewed = [r for r in counted if r.answers is not None]
    reviewers = {r.reviewer_id for r in reviewed if r.reviewer_id is not None}
    answers = [value for r in reviewed if r.answers is not None for value in r.answers.values()]
    ratio = sum(answers) / len(answers) if answers else 0.0
    tier = next(
        (
            rule.tier
            for rule in rules.tiers
            if len(counted) >= rule.min_completed
            and len(reviewers) >= rule.min_distinct_reviewers
            and ratio >= rule.min_positive_ratio
        ),
        rules.default,
    )
    return Evaluation(
        tier=tier,
        completed=len(counted),
        distinct_reviewers=len(reviewers),
        positive_ratio=ratio,
        window_start=window_start,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/standing tests/integration/test_standing_records.py tests/api/engagements -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(standing): pure tier rules engine and standing records" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 3: Standing tables and recalculation on feedback

**Files:**
- Create: `backend/alembic/versions/0009_standing.py`, `backend/app/modules/standing/models.py`, `repository.py`, `schemas.py`, `recalculation.py`, `handlers.py`, `service.py`
- Modify: `backend/app/core/context.py`, `backend/app/core/outbox/processing.py`, `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/service.py`, `backend/app/models_registry.py`, `backend/app/wiring.py`
- Test: `backend/tests/integration/test_outbox_event_scope.py`, `backend/tests/api/standing/__init__.py`, `backend/tests/api/standing/test_recalculation.py`

**Interfaces:**
- Consumes: `evaluate` (Task 2), `standing_records` (Task 2), `active_tiering`/`TieringPolicy` (Task 1), `FeedbackSubmitted` (`engagements.schemas`).
- Produces:
  - `app.core.context.event_scope(event_id)` and `get_event_id() -> UUID | None`. `process_event` binds the event id while a handler runs.
  - Passport functions, all exported from `passport.service`:
    - `lock_standing_tier(session, worker_id) -> StandingTier | None` (takes a row lock)
    - `current_standing_tier(session, worker_id) -> StandingTier | None`
    - `set_standing_tier(session, worker_id, tier)`
  - Models `StandingChange` (append-only) and `SkillEvidence`. Migration 0009 creates both tables. `skill_evidence` is used in Task 4.
  - `StandingChangeRepository(session)`: `add`, `list_for_worker(worker_id, limit)`.
  - Events:
    - `StandingChanged(previous_tier, new_tier, policy_version)`, `event_type = "standing.standing_changed"`, `aggregate_id` = worker.
    - `SkillVerified(skill_id)`, `event_type = "standing.skill_verified"`, `aggregate_id` = worker. Emitted in Task 4.
  - `recalculation.recalculate(session, worker_id, *, policy, trigger_event_id) -> StandingChange | None`.
  - `handlers.register(registry)`: handler `standing.recalculate` on `FeedbackSubmitted`.

The worker row is locked (`SELECT … FOR UPDATE`) before evaluating, so concurrent recalculations of one worker run one after the other. The second one sees the tier the first stored and records no change. `standing_changes` has no `updated_at`, because it is never updated. Its `actor_id` has no `ON DELETE SET NULL`, because a cascading update would hit the append-only trigger, and staff accounts are revoked, never deleted.

- [ ] **Step 1: Event scope in the core**

In `backend/app/core/context.py`, add:

```python
_event_id: ContextVar[UUID | None] = ContextVar("event_id", default=None)


def get_event_id() -> UUID | None:
    """The outbox event the current handler is processing, if any."""
    return _event_id.get()


@contextmanager
def event_scope(event_id: UUID) -> Iterator[None]:
    token = _event_id.set(event_id)
    try:
        yield
    finally:
        _event_id.reset(token)
```

In `backend/app/core/outbox/processing.py`, import `event_scope` and change the handler call to:

```python
        with correlation_scope(event.correlation_id), event_scope(event.event_id):
            await registry.get(handler_name)(session, event.payload)
```

`backend/tests/integration/test_outbox_event_scope.py`:

```python
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import get_event_id
from app.core.outbox.events import DomainEvent
from app.core.outbox.processing import process_event
from app.core.outbox.registry import HandlerRegistry
from app.core.outbox.writer import emit_event


class _Ping(DomainEvent):
    event_type: ClassVar[str] = "test.ping"


async def test_handlers_see_the_event_they_are_processing(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    seen: list[UUID | None] = []

    async def handler(session: AsyncSession, payload: dict[str, Any]) -> None:
        seen.append(get_event_id())

    registry = HandlerRegistry()
    registry.register(_Ping, "test.record_event_id", handler)
    async with sessionmaker() as session, session.begin():
        row = await emit_event(session, _Ping(aggregate_id=uuid4()))
        await session.flush()
        event_id = row.event_id

    await process_event(sessionmaker, registry, event_id, "test.record_event_id")

    assert seen == [event_id]
    assert get_event_id() is None
```

- [ ] **Step 2: Tables and models**

`backend/app/modules/standing/models.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.core.time import utcnow
from app.modules.passport.service import StandingTier


class StandingChange(UUIDPrimaryKeyMixin, Base):
    """Append-only history of a worker's tier (FR-3.3, spec §6.3). A DB
    trigger rejects UPDATE and DELETE."""

    __tablename__ = "standing_changes"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    previous_tier: Mapped[StandingTier] = mapped_column(pg_enum(StandingTier), nullable=False)
    new_tier: Mapped[StandingTier] = mapped_column(pg_enum(StandingTier), nullable=False)
    contributing_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_configs.id", ondelete="RESTRICT")
    )
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="RESTRICT")
    )
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_standing_changes_worker_created", "worker_id", "created_at"),
    )


class SkillEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reviewer saw this worker demonstrate this skill on an engagement
    (FR-2.2). Distinct reviewers per (worker, skill) drive verification."""

    __tablename__ = "skill_evidence"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint(
            "worker_id", "skill_id", "reviewer_id", name="uq_skill_evidence_worker_skill_reviewer"
        ),
    )
```

`backend/alembic/versions/0009_standing.py`:

```python
"""standing: append-only standing_changes and skill_evidence

Revision ID: 0009_standing
Revises: 0008_policies
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_standing"
down_revision: str | None = "0008_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
# Created by 0005_passport; reused here.
_TIER = postgresql.ENUM("unrated", "tier_1", "tier_2", name="standingtier", create_type=False)


def upgrade() -> None:
    op.create_table(
        "standing_changes",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("previous_tier", _TIER, nullable=False),
        sa.Column("new_tier", _TIER, nullable=False),
        sa.Column("contributing_factors", postgresql.JSONB(), nullable=False),
        sa.Column("policy_version_id", _UUID, nullable=True),
        sa.Column("trigger_event_id", _UUID, nullable=True),
        sa.Column("actor_id", _UUID, nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_standing_changes"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_standing_changes_worker_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"], ["policy_configs.id"],
            name="fk_standing_changes_policy_version_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["user_accounts.id"], name="fk_standing_changes_actor_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_standing_changes_worker_created", "standing_changes", ["worker_id", "created_at"]
    )
    # forbid_mutation() was created by 0001_core for audit_log.
    op.execute(
        "CREATE TRIGGER standing_changes_append_only BEFORE UPDATE OR DELETE "
        "ON standing_changes FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
    )

    op.create_table(
        "skill_evidence",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("skill_id", _UUID, nullable=False),
        sa.Column("engagement_id", _UUID, nullable=False),
        sa.Column("reviewer_id", _UUID, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_evidence"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_skill_evidence_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_skill_evidence_skill_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name="fk_skill_evidence_engagement_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["user_accounts.id"], name="fk_skill_evidence_reviewer_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "worker_id", "skill_id", "reviewer_id", name="uq_skill_evidence_worker_skill_reviewer"
        ),
    )


def downgrade() -> None:
    op.drop_table("skill_evidence")
    op.execute("DROP TRIGGER IF EXISTS standing_changes_append_only ON standing_changes")
    op.drop_index("ix_standing_changes_worker_created", table_name="standing_changes")
    op.drop_table("standing_changes")
```

Add `from app.modules.standing import models as standing_models` to `backend/app/models_registry.py`, and add `"standing_models"` to its `__all__`.

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 3: Write the failing tests**

`backend/tests/api/standing/__init__.py`: empty file.

`backend/tests/api/standing/test_recalculation.py`:

```python
import asyncio
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.engagements.models import Engagement
from app.modules.governance.service import active_tiering
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import StandingTier
from app.modules.passport.models import Worker
from app.modules.standing.models import StandingChange
from app.modules.standing.recalculation import recalculate
from tests.support import (
    POSITIVE_ANSWERS,
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def _completed_engagement(
    session: AsyncSession,
) -> tuple[UserAccount, Worker, Engagement]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    return pm, worker, engagement


async def test_positive_feedback_raises_the_tier_once(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _completed_engagement(session)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": POSITIVE_ANSWERS},
        headers=bearer(settings, pm),
    )
    feedback_event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "engagements.feedback_submitted")
        )
    ).one()
    await drain()

    assert response.status_code == 201
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1
    change = (await session.scalars(select(StandingChange))).one()
    policy = await active_tiering(session)
    assert (change.previous_tier, change.new_tier) == (StandingTier.UNRATED, StandingTier.TIER_1)
    assert change.policy_version_id == policy.id
    assert change.trigger_event_id == feedback_event.event_id
    assert change.actor_id is None
    assert change.contributing_factors["completed"] == 1
    assert change.contributing_factors["policy_version"] == 1
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "standing.changed"))
    ).one()
    assert (audit.target_id, audit.before, audit.after) == (
        worker.id,
        {"tier": "unrated"},
        {"tier": "tier_1", "policy_version": 1},
    )
    changed = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "standing.standing_changed")
        )
    ).one()
    assert changed.payload["new_tier"] == "tier_1"


async def test_negative_feedback_leaves_the_worker_unrated(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _completed_engagement(session)

    await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": {k: False for k in POSITIVE_ANSWERS}},
        headers=bearer(settings, pm),
    )
    await drain()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.UNRATED
    assert (await session.scalars(select(StandingChange))).all() == []


async def test_recalculating_again_records_nothing_new(session: AsyncSession) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    policy = await active_tiering(session)

    first = await recalculate(session, worker.id, policy=policy, trigger_event_id=None)
    second = await recalculate(session, worker.id, policy=policy, trigger_event_id=None)
    await session.commit()

    assert first is not None
    assert second is None
    assert len((await session.scalars(select(StandingChange))).all()) == 1


async def test_excluded_feedback_does_not_count(session: AsyncSession) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id, excluded=True)

    change = await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )

    assert change is None


async def test_concurrent_recalculations_record_one_change(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    async def run() -> None:
        async with sessionmaker() as s, s.begin():
            await recalculate(s, worker.id, policy=await active_tiering(s), trigger_event_id=None)

    await asyncio.gather(run(), run())

    assert len((await session.scalars(select(StandingChange))).all()) == 1


async def test_standing_changes_are_append_only(session: AsyncSession) -> None:
    pm, worker, engagement = await _completed_engagement(session)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate(
        session, worker.id, policy=await active_tiering(session), trigger_event_id=None
    )
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(update(StandingChange).values(override_reason="edited"))
    await session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(StandingChange))
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/integration/test_outbox_event_scope.py tests/api/standing -v`
Expected: FAIL. `app.modules.standing.recalculation` does not exist yet. If Step 1 is not in place, you will also see `ImportError: cannot import name 'get_event_id'`.

- [ ] **Step 5: Implement**

Append to `backend/app/modules/passport/queries.py` (imports: `StandingTier`, `Worker` if missing):

```python
async def lock_standing_tier(session: AsyncSession, worker_id: UUID) -> StandingTier | None:
    """Row-locks the worker so concurrent recalculations of one worker serialize."""
    return await session.scalar(
        select(Worker.standing_tier).where(Worker.id == worker_id).with_for_update()
    )


async def current_standing_tier(session: AsyncSession, worker_id: UUID) -> StandingTier | None:
    return await session.scalar(select(Worker.standing_tier).where(Worker.id == worker_id))


async def set_standing_tier(session: AsyncSession, worker_id: UUID, tier: StandingTier) -> None:
    worker = await WorkerRepository(session).get(worker_id)
    if worker is not None:
        worker.standing_tier = tier
```

Export all three from `backend/app/modules/passport/service.py`.

`backend/app/modules/standing/schemas.py`:

```python
from typing import ClassVar
from uuid import UUID

from app.core.outbox.events import DomainEvent
from app.modules.passport.service import StandingTier


class StandingChanged(DomainEvent):
    """aggregate_id is the worker."""

    event_type: ClassVar[str] = "standing.standing_changed"
    previous_tier: StandingTier
    new_tier: StandingTier
    policy_version: int | None


class SkillVerified(DomainEvent):
    """aggregate_id is the worker."""

    event_type: ClassVar[str] = "standing.skill_verified"
    skill_id: UUID
```

`backend/app/modules/standing/repository.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.standing.models import StandingChange


class StandingChangeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, change: StandingChange) -> StandingChange:
        self.session.add(change)
        return change

    async def list_for_worker(self, worker_id: UUID, limit: int) -> list[StandingChange]:
        stmt = (
            select(StandingChange)
            .where(StandingChange.worker_id == worker_id)
            .order_by(StandingChange.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())
```

`backend/app/modules/standing/recalculation.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.schemas import TieringPolicy
from app.modules.passport.service import StandingTier, lock_standing_tier, set_standing_tier
from app.modules.standing.models import StandingChange
from app.modules.standing.repository import StandingChangeRepository
from app.modules.standing.rules import evaluate
from app.modules.standing.schemas import StandingChanged


async def recalculate(
    session: AsyncSession,
    worker_id: UUID,
    *,
    policy: TieringPolicy,
    trigger_event_id: UUID | None,
) -> StandingChange | None:
    """Re-evaluates one worker (spec §7.3). Writes a standing change only when
    the tier moves. The worker row lock serializes concurrent runs."""
    current = await lock_standing_tier(session, worker_id)
    if current is None:
        return None
    evaluation = evaluate(await standing_records(session, worker_id), policy.rules, utcnow().date())
    new_tier = StandingTier(evaluation.tier)
    if new_tier is current:
        return None
    change = StandingChangeRepository(session).add(
        StandingChange(
            worker_id=worker_id,
            previous_tier=current,
            new_tier=new_tier,
            contributing_factors={**evaluation.factors(), "policy_version": policy.version},
            policy_version_id=policy.id,
            trigger_event_id=trigger_event_id,
        )
    )
    await set_standing_tier(session, worker_id, new_tier)
    await session.flush()
    await write_audit(
        session,
        actor=None,
        action="standing.changed",
        target_type="worker",
        target_id=worker_id,
        before={"tier": current.value},
        after={"tier": new_tier.value, "policy_version": policy.version},
    )
    await emit_event(
        session,
        StandingChanged(
            aggregate_id=worker_id,
            previous_tier=current,
            new_tier=new_tier,
            policy_version=policy.version,
        ),
    )
    return change
```

`backend/app/modules/standing/handlers.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_event_id
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.schemas import FeedbackSubmitted
from app.modules.governance.service import active_tiering
from app.modules.standing.recalculation import recalculate


def register(registry: HandlerRegistry) -> None:
    async def recalculate_on_feedback(session: AsyncSession, payload: dict[str, Any]) -> None:
        await recalculate(
            session,
            UUID(payload["worker_id"]),
            policy=await active_tiering(session),
            trigger_event_id=get_event_id(),
        )

    registry.register(FeedbackSubmitted, "standing.recalculate", recalculate_on_feedback)
```

`backend/app/modules/standing/service.py`:

```python
"""Public interface of the standing module."""

from app.modules.standing.schemas import SkillVerified, StandingChanged

__all__ = ["SkillVerified", "StandingChanged"]
```

In `backend/app/wiring.py`, import `from app.modules.standing import handlers as standing_handlers` and call `standing_handlers.register(registry)` in `build_registry` after the engagements registration.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/integration/test_outbox_event_scope.py tests/api/standing tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 7: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(standing): append-only standing changes and recalculation on feedback" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 4: Skill evidence and verification

**Files:**
- Create: `backend/app/modules/standing/evidence.py`
- Modify: `backend/app/modules/standing/repository.py`, `backend/app/modules/standing/handlers.py`, `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/service.py`
- Test: `backend/tests/api/standing/test_skill_verification.py`

**Interfaces:**
- Consumes: `SkillEvidence` model and `SkillVerified` event (Task 3), `active_tiering` (Task 1).
- Produces:
  - `passport.queries.verify_skill(session, worker_id, skill_id) -> bool`. It locks the claim. It returns True only when it changes the claim to `bonarda_verified`, and False if the claim is missing or already verified. It is exported from `passport.service`.
  - `SkillEvidenceRepository(session)`:
    - `add(worker_id, skill_id, engagement_id, reviewer_id)`: insert, doing nothing on conflict.
    - `distinct_reviewers(worker_id, skill_id) -> int`.
    - `pairs_meeting(min_reviewers) -> list[tuple[UUID, UUID]]`.
  - In `evidence.py`:
    - `mark_verified(session, worker_id, skill_id) -> bool`: calls `verify_skill`, audits `skill.verified` and emits `SkillVerified`.
    - `record_skill_evidence(session, *, engagement_id, worker_id, reviewer_id, skill_ids, min_reviewers) -> list[UUID]`.
    - `promote_skills(session, min_reviewers) -> int` (used in Task 5).
  - Handler `standing.record_skill_evidence` on `FeedbackSubmitted`.

Evidence is keyed by `(worker, skill, reviewer)`, not by `skill_claim_id` as spec §6.1 describes. A worker may delete a self-reported claim, and evidence should neither block that deletion nor be lost if they claim the skill again. Task 8 records this as a deviation. Verification needs the claim to exist when the handler runs.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/standing/test_skill_verification.py`:

```python
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.standing.models import SkillEvidence
from tests.support import (
    POSITIVE_ANSWERS,
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def _review(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    *,
    pm: UserAccount,
    worker_id: UUID,
    skill_id: UUID,
) -> None:
    project = await make_project(session, staff=[pm], name=f"Project {uuid4().hex[:6]}")
    engagement = await make_engagement(session, worker_id=worker_id, project_id=project.id)
    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": POSITIVE_ANSWERS, "skill_ids_demonstrated": [str(skill_id)]},
        headers=bearer(settings, pm),
    )
    assert response.status_code == 201


async def _claim_status(session: AsyncSession, worker_id: UUID) -> VerificationStatus:
    claim = (await session.scalars(select(SkillClaim).where(SkillClaim.worker_id == worker_id))).one()
    await session.refresh(claim)
    return claim.verification_status


async def test_two_distinct_reviewers_verify_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)

    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await drain()
    after_one = await _claim_status(session, worker.id)
    await _review(client, session, settings, pm=kwame, worker_id=worker.id, skill_id=skill.id)
    await drain()

    assert after_one is VerificationStatus.SELF_REPORTED
    assert await _claim_status(session, worker.id) is VerificationStatus.BONARDA_VERIFIED
    verified = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "standing.skill_verified")
        )
    ).one()
    assert verified.payload["skill_id"] == str(skill.id)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "skill.verified"))
    ).one()
    assert (audit.target_id, audit.after) == (worker.id, {"skill_id": str(skill.id)})


async def test_the_same_reviewer_counts_once(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)

    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await drain()

    assert await _claim_status(session, worker.id) is VerificationStatus.SELF_REPORTED
    assert len((await session.scalars(select(SkillEvidence))).all()) == 1


async def test_a_removed_claim_is_not_verified_but_evidence_is_kept(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await _review(client, session, settings, pm=kwame, worker_id=worker.id, skill_id=skill.id)
    await session.execute(delete(SkillClaim).where(SkillClaim.worker_id == worker.id))
    await session.commit()

    await drain()

    assert len((await session.scalars(select(SkillEvidence))).all()) == 2
    assert (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "standing.skill_verified")
        )
    ).all() == []


async def test_verified_skill_shows_on_the_worker_passport(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    for _ in range(2):
        pm = await make_user(session, role=UserRole.PM)
        await _review(client, session, settings, pm=pm, worker_id=worker.id, skill_id=skill.id)
    await drain()

    me = await client.get("/api/v1/workers/me", headers=bearer(settings, account))

    assert me.json()["skills"][0]["verification_status"] == "bonarda_verified"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/standing/test_skill_verification.py -v`
Expected: FAIL. The claims stay `self_reported` and no `SkillEvidence` rows exist.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/passport/queries.py` (imports `SkillClaim`, `VerificationStatus`):

```python
async def verify_skill(session: AsyncSession, worker_id: UUID, skill_id: UUID) -> bool:
    """Marks a claim bonarda_verified (FR-2.2). True only if this call changed it."""
    claim = await session.scalar(
        select(SkillClaim)
        .where(SkillClaim.worker_id == worker_id, SkillClaim.skill_id == skill_id)
        .with_for_update()
    )
    if claim is None or claim.verification_status is VerificationStatus.BONARDA_VERIFIED:
        return False
    claim.verification_status = VerificationStatus.BONARDA_VERIFIED
    return True
```

Export `verify_skill` from `backend/app/modules/passport/service.py`.

Append to `backend/app/modules/standing/repository.py` (imports: `func` from sqlalchemy, `insert as pg_insert` from `sqlalchemy.dialects.postgresql`, `SkillEvidence`):

```python
class SkillEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, *, worker_id: UUID, skill_id: UUID, engagement_id: UUID, reviewer_id: UUID
    ) -> None:
        await self.session.execute(
            pg_insert(SkillEvidence)
            .values(
                worker_id=worker_id,
                skill_id=skill_id,
                engagement_id=engagement_id,
                reviewer_id=reviewer_id,
            )
            .on_conflict_do_nothing(constraint="uq_skill_evidence_worker_skill_reviewer")
        )

    async def distinct_reviewers(self, worker_id: UUID, skill_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count(func.distinct(SkillEvidence.reviewer_id))).where(
                SkillEvidence.worker_id == worker_id,
                SkillEvidence.skill_id == skill_id,
                SkillEvidence.reviewer_id.is_not(None),
            )
        )
        return int(count or 0)

    async def pairs_meeting(self, min_reviewers: int) -> list[tuple[UUID, UUID]]:
        stmt = (
            select(SkillEvidence.worker_id, SkillEvidence.skill_id)
            .where(SkillEvidence.reviewer_id.is_not(None))
            .group_by(SkillEvidence.worker_id, SkillEvidence.skill_id)
            .having(func.count(func.distinct(SkillEvidence.reviewer_id)) >= min_reviewers)
        )
        return [(worker_id, skill_id) for worker_id, skill_id in await self.session.execute(stmt)]
```

`backend/app/modules/standing/evidence.py`:

```python
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.modules.passport.service import verify_skill
from app.modules.standing.repository import SkillEvidenceRepository
from app.modules.standing.schemas import SkillVerified


async def mark_verified(session: AsyncSession, worker_id: UUID, skill_id: UUID) -> bool:
    if not await verify_skill(session, worker_id, skill_id):
        return False
    await write_audit(
        session,
        actor=None,
        action="skill.verified",
        target_type="worker",
        target_id=worker_id,
        after={"skill_id": str(skill_id)},
    )
    await emit_event(session, SkillVerified(aggregate_id=worker_id, skill_id=skill_id))
    return True


async def record_skill_evidence(
    session: AsyncSession,
    *,
    engagement_id: UUID,
    worker_id: UUID,
    reviewer_id: UUID | None,
    skill_ids: Sequence[UUID],
    min_reviewers: int,
) -> list[UUID]:
    """FR-2.2: a skill becomes bonarda_verified once distinct reviewers who saw
    it demonstrated reach the policy threshold. Returns newly verified skills."""
    if reviewer_id is None:
        return []
    evidence = SkillEvidenceRepository(session)
    verified = []
    for skill_id in dict.fromkeys(skill_ids):
        await evidence.add(
            worker_id=worker_id,
            skill_id=skill_id,
            engagement_id=engagement_id,
            reviewer_id=reviewer_id,
        )
        if await evidence.distinct_reviewers(
            worker_id, skill_id
        ) >= min_reviewers and await mark_verified(session, worker_id, skill_id):
            verified.append(skill_id)
    return verified


async def promote_skills(session: AsyncSession, min_reviewers: int) -> int:
    """Verifies every claim whose evidence already meets the threshold, e.g.
    after a policy lowers it."""
    promoted = 0
    for worker_id, skill_id in await SkillEvidenceRepository(session).pairs_meeting(min_reviewers):
        if await mark_verified(session, worker_id, skill_id):
            promoted += 1
    return promoted
```

In `backend/app/modules/standing/handlers.py`, add this inside `register` (import `record_skill_evidence`):

```python
    async def record_evidence(session: AsyncSession, payload: dict[str, Any]) -> None:
        policy = await active_tiering(session)
        reviewer = payload.get("reviewer_id")
        await record_skill_evidence(
            session,
            engagement_id=UUID(payload["aggregate_id"]),
            worker_id=UUID(payload["worker_id"]),
            reviewer_id=UUID(reviewer) if reviewer else None,
            skill_ids=[UUID(s) for s in payload.get("skill_ids_demonstrated", [])],
            min_reviewers=policy.rules.skill_verification.min_distinct_reviewers,
        )

    registry.register(FeedbackSubmitted, "standing.record_skill_evidence", record_evidence)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/standing tests/api/passport/test_skills.py -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(standing): skill evidence and distinct-reviewer verification" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 5: Re-evaluation on policy activation and nightly

**Files:**
- Modify: `backend/app/modules/standing/recalculation.py`, `backend/app/modules/standing/handlers.py`, `backend/app/modules/standing/service.py`, `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/service.py`, `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`
- Test: `backend/tests/api/standing/test_reevaluation.py`

**Interfaces:**
- Consumes: `recalculate` (Task 3), `promote_skills` (Task 4), `PolicyActivated` (Task 1).
- Produces:
  - `passport.queries.standing_worker_ids(session) -> list[UUID]`: workers with status `active` or `dormant`. Exported from `passport.service`.
  - `recalculation.recalculate_all(session, *, policy, trigger_event_id) -> int`: the number of workers whose tier changed. It also runs `promote_skills` with the policy's threshold.
  - `standing.service.recalculate_all_standing(session) -> int`: runs `recalculate_all` against the active policy, with no trigger event.
  - Handler `standing.recalculate_all` on `PolicyActivated`. It acts only when `kind == "tiering"`.
  - Arq cron `recalculate_standing`, nightly at 03:00 UTC.

The spec re-evaluates on policy activation (§7.7). The nightly run is an addition, recorded as a deviation in Task 8. Without it, a tier would outlive the feedback window: nothing else fires when feedback ages out of `window_months`. Both runs process every worker in one transaction. That is fine at the pilot's 5,000 profiles; batching is a Task 8 carry-forward row.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/standing/test_reevaluation.py`:

```python
import copy
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.governance.service import active_tiering
from app.modules.passport.enums import StandingTier, VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.standing.models import SkillEvidence, StandingChange
from app.modules.standing.service import recalculate_all_standing
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


def _tiering(**changes: Any) -> dict[str, Any]:
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering"))
    for path, value in changes.items():
        section, key = path.split("__")
        target = rules["tiers"][1] if section == "tier_1" else rules[section]
        target[key] = value
    return rules


async def _activate(
    client: AsyncClient, session: AsyncSession, settings: Settings, rules: dict[str, Any]
) -> None:
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/tiering/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    version = proposed.json()["version"]
    activated = await client.post(
        f"/api/v1/policies/tiering/versions/{version}/activate", headers=bearer(settings, approver)
    )
    assert activated.status_code == 200


async def test_a_stricter_policy_lowers_existing_tiers(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate_all_standing(session)
    await session.commit()
    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.TIER_1

    await _activate(client, session, settings, _tiering(tier_1__min_completed=2))
    activated = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.policy_activated")
        )
    ).one()
    await drain()

    await session.refresh(worker)
    assert worker.standing_tier is StandingTier.UNRATED
    latest = (
        await session.scalars(select(StandingChange).order_by(StandingChange.created_at.desc()))
    ).first()
    assert latest is not None
    assert latest.trigger_event_id == activated.event_id
    assert latest.policy_version_id == (await active_tiering(session)).id


async def test_a_lower_threshold_verifies_skills_with_existing_evidence(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    session.add(
        SkillEvidence(
            worker_id=worker.id, skill_id=skill.id, engagement_id=engagement.id, reviewer_id=pm.id
        )
    )
    await session.commit()

    await _activate(
        client, session, settings, _tiering(skill_verification__min_distinct_reviewers=1)
    )
    await drain()

    claim = (await session.scalars(select(SkillClaim))).one()
    await session.refresh(claim)
    assert claim.verification_status is VerificationStatus.BONARDA_VERIFIED


async def test_a_matching_policy_does_not_touch_standing(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching"))
    await client.post(
        "/api/v1/policies/matching/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    await client.post(
        "/api/v1/policies/matching/versions/2/activate", headers=bearer(settings, approver)
    )

    await drain()

    assert (await session.scalars(select(StandingChange))).all() == []


async def test_nightly_run_drops_a_tier_once_feedback_ages_out(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session)).id,
        completed_at=utcnow() - timedelta(days=30),
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    assert await recalculate_all_standing(session) == 1
    engagement.completed_at = utcnow() - timedelta(days=800)
    await session.commit()

    changed = await recalculate_all_standing(session)
    await session.commit()

    await session.refresh(worker)
    assert changed == 1
    assert worker.standing_tier is StandingTier.UNRATED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/standing/test_reevaluation.py -v`
Expected: FAIL. `ImportError: cannot import name 'recalculate_all_standing'`.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/passport/queries.py`:

```python
async def standing_worker_ids(session: AsyncSession) -> list[UUID]:
    """Workers whose standing is maintained: in the talent pool."""
    rows = await session.scalars(
        select(Worker.id).where(Worker.status.in_((WorkerStatus.ACTIVE, WorkerStatus.DORMANT)))
    )
    return list(rows.all())
```

Export `standing_worker_ids` from `backend/app/modules/passport/service.py`.

Append to `backend/app/modules/standing/recalculation.py` (import `promote_skills` from `app.modules.standing.evidence`, `standing_worker_ids` from `passport.service`, `active_tiering` from `governance.service`):

```python
async def recalculate_all(
    session: AsyncSession, *, policy: TieringPolicy, trigger_event_id: UUID | None
) -> int:
    """Re-evaluates every worker in the pool and promotes skills whose
    evidence meets the policy's threshold. Returns how many tiers changed."""
    changed = 0
    for worker_id in await standing_worker_ids(session):
        if await recalculate(session, worker_id, policy=policy, trigger_event_id=trigger_event_id):
            changed += 1
    await promote_skills(session, policy.rules.skill_verification.min_distinct_reviewers)
    return changed


async def recalculate_all_standing(session: AsyncSession) -> int:
    """Nightly: tiers follow the feedback window even when no event fires."""
    return await recalculate_all(
        session, policy=await active_tiering(session), trigger_event_id=None
    )
```

In `backend/app/modules/standing/handlers.py`, add this inside `register` (import `PolicyActivated` from `app.modules.governance.schemas`, and `recalculate_all` from the recalculation module):

```python
    async def recalculate_on_policy(session: AsyncSession, payload: dict[str, Any]) -> None:
        if payload["kind"] != "tiering":
            return
        await recalculate_all(
            session, policy=await active_tiering(session), trigger_event_id=get_event_id()
        )

    registry.register(PolicyActivated, "standing.recalculate_all", recalculate_on_policy)
```

Export `recalculate_all_standing` from `backend/app/modules/standing/service.py`.

Append to `backend/app/worker/jobs.py` (import `recalculate_all_standing` from `app.modules.standing.service`):

```python
async def recalculate_standing(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await recalculate_all_standing(session)
```

In `backend/app/worker/settings.py`, import it and add `cron(recalculate_standing, hour={3}, minute={0})` to `cron_jobs`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/standing tests/api/governance -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(standing): re-evaluate on tiering policy activation and nightly" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 6: Standing explanation API

**Files:**
- Create: `backend/app/modules/standing/explanation.py`, `backend/app/modules/standing/router.py`
- Modify: `backend/app/modules/standing/schemas.py`, `backend/app/modules/standing/repository.py` (Task 3's `list_for_worker` is used), `backend/app/main.py`
- Test: `backend/tests/api/standing/test_explanation.py`

**Interfaces:**
- Consumes: `evaluate`, `standing_records`, `active_tiering`, `policy_versions`, `current_standing_tier`, `StandingChangeRepository`, `require_visibility`/`Visibility`, `CurrentActor`.
- Produces:
  - Schemas `StandingFactors`, `StandingChangeRead`, `StandingExplanation`.
  - `explanation.standing_explanation(session, worker_id) -> StandingExplanation`.
  - Routes:
    - `GET /api/v1/workers/me/standing`: worker accounts only; others get 403 `not_a_worker`.
    - `GET /api/v1/workers/{worker_id}/standing`: guard `DETAIL`. The worker's own `SELF` level passes.

The explanation (spec §2.1 #2, FR-1.3):
- the stored tier;
- the active policy's version, window and tier thresholds, so a worker sees what the next tier needs;
- factors from a live evaluation under the active policy;
- the 50 most recent standing changes, newest first. Each carries its factors, its policy version and whether it was automated.

A PM with summary-level visibility gets 404, because standing factors are detail-level (spec §7.1).

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/standing/test_explanation.py`:

```python
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import Project
from app.modules.identity.models import UserAccount
from app.modules.passport.models import Worker
from app.modules.standing.service import recalculate_all_standing
from tests.support import (
    bearer,
    make_engagement,
    make_feedback,
    make_project,
    make_ready_worker,
    make_user,
    make_worker,
)


async def _tier_1_worker(
    session: AsyncSession,
) -> tuple[UserAccount, Worker, UserAccount, Project]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, account = await make_ready_worker(session)
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    await recalculate_all_standing(session)
    await session.commit()
    return pm, worker, account, project


async def test_worker_sees_tier_factors_thresholds_and_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, worker, account, _ = await _tier_1_worker(session)

    response = await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))

    body = response.json()
    assert response.status_code == 200
    assert (body["worker_id"], body["tier"], body["policy_version"]) == (str(worker.id), "tier_1", 1)
    assert body["window_months"] == 24
    assert [t["tier"] for t in body["tiers"]] == ["tier_2", "tier_1"]
    assert body["factors"]["completed"] == 1
    assert body["factors"]["distinct_reviewers"] == 1
    assert body["factors"]["positive_ratio"] == 1.0
    (change,) = body["history"]
    assert (change["previous_tier"], change["new_tier"], change["policy_version"]) == (
        "unrated",
        "tier_1",
        1,
    )
    assert change["automated"] is True


async def test_detail_viewers_can_read_a_workers_standing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, worker, _, _ = await _tier_1_worker(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    as_pm = await client.get(f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, pm))
    as_ops = await client.get(
        f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, ops)
    )

    assert (as_pm.status_code, as_ops.status_code) == (200, 200)


async def test_summary_level_pm_and_other_workers_get_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, worker, _, _ = await _tier_1_worker(session)
    stranger_pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[stranger_pm], data_region="GH", name="Nearby")
    _, other = await make_worker(session, email="other@example.com")

    summary = await client.get(
        f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, stranger_pm)
    )
    peer = await client.get(f"/api/v1/workers/{worker.id}/standing", headers=bearer(settings, other))

    assert (summary.status_code, peer.status_code) == (404, 404)
    assert summary.json()["code"] == "worker_not_found"


async def test_staff_have_no_own_standing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.get("/api/v1/workers/me/standing", headers=bearer(settings, ops))

    assert (response.status_code, response.json()["code"]) == (403, "not_a_worker")


async def test_a_new_worker_is_unrated_with_empty_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)

    body = (
        await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
    ).json()

    assert (body["tier"], body["history"], body["factors"]["completed"]) == ("unrated", [], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/standing/test_explanation.py -v`
Expected: FAIL with 404 for `/api/v1/workers/me/standing`, because no route exists.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/standing/schemas.py` (imports: `date`, `datetime`, `Any`, `BaseModel`, `TierRule` from `governance.schemas`):

```python
class StandingFactors(BaseModel):
    completed: int
    distinct_reviewers: int
    positive_ratio: float
    window_start: date


class StandingChangeRead(BaseModel):
    previous_tier: StandingTier
    new_tier: StandingTier
    factors: dict[str, Any]
    policy_version: int | None
    automated: bool
    override_reason: str | None
    occurred_at: datetime


class StandingExplanation(BaseModel):
    """Tier, signals and policy version (spec §2.1 #2, FR-1.3)."""

    worker_id: UUID
    tier: StandingTier
    policy_version: int
    window_months: int
    tiers: list[TierRule]
    factors: StandingFactors
    history: list[StandingChangeRead]
```

`backend/app/modules/standing/explanation.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.time import utcnow
from app.modules.engagements.service import standing_records
from app.modules.governance.service import active_tiering, policy_versions
from app.modules.passport.service import current_standing_tier
from app.modules.standing.repository import StandingChangeRepository
from app.modules.standing.rules import evaluate
from app.modules.standing.schemas import (
    StandingChangeRead,
    StandingExplanation,
    StandingFactors,
)

HISTORY_LIMIT = 50


async def standing_explanation(session: AsyncSession, worker_id: UUID) -> StandingExplanation:
    tier = await current_standing_tier(session, worker_id)
    if tier is None:
        raise NotFound("Worker not found", code="worker_not_found")
    policy = await active_tiering(session)
    evaluation = evaluate(await standing_records(session, worker_id), policy.rules, utcnow().date())
    changes = await StandingChangeRepository(session).list_for_worker(worker_id, HISTORY_LIMIT)
    versions = await policy_versions(
        session, [c.policy_version_id for c in changes if c.policy_version_id is not None]
    )
    return StandingExplanation(
        worker_id=worker_id,
        tier=tier,
        policy_version=policy.version,
        window_months=policy.rules.window_months,
        tiers=policy.rules.tiers,
        factors=StandingFactors(
            completed=evaluation.completed,
            distinct_reviewers=evaluation.distinct_reviewers,
            positive_ratio=round(evaluation.positive_ratio, 4),
            window_start=evaluation.window_start,
        ),
        history=[
            StandingChangeRead(
                previous_tier=c.previous_tier,
                new_tier=c.new_tier,
                factors=c.contributing_factors,
                policy_version=versions.get(c.policy_version_id) if c.policy_version_id else None,
                automated=c.actor_id is None,
                override_reason=c.override_reason,
                occurred_at=c.created_at,
            )
            for c in changes
        ],
    )
```

`backend/app/modules/standing/router.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db.session import SessionDep
from app.core.errors import Forbidden
from app.modules.identity.service import CurrentActor, Visibility, require_visibility
from app.modules.standing.explanation import standing_explanation
from app.modules.standing.schemas import StandingExplanation

router = APIRouter(prefix="/api/v1", tags=["standing"])


@router.get("/workers/me/standing")
async def my_standing(actor: CurrentActor, session: SessionDep) -> StandingExplanation:
    if actor.worker_id is None:
        raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
    return await standing_explanation(session, actor.worker_id)


@router.get("/workers/{worker_id}/standing")
async def worker_standing(
    worker_id: UUID,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> StandingExplanation:
    return await standing_explanation(session, worker_id)
```

`/workers/me/standing` is declared first. It takes `CurrentActor` rather than a worker-only permission, so staff calling it get 403 `not_a_worker` rather than a permission error.

In `backend/app/main.py`, import `from app.modules.standing.router import router as standing_router` and add `app.include_router(standing_router)` after the governance router.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/standing tests/api/test_visibility_guard.py -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(standing): standing explanation for workers and detail viewers" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 7: Carry-forward: engagement history and the reactivation fast path

**Files:**
- Modify: `backend/app/modules/engagements/repository.py`, `backend/app/modules/engagements/engagements.py`
- Test: `backend/tests/api/engagements/test_engagement_paths.py`

**Interfaces:**
- Consumes: `EngagementService.create`, `EngagementRepository.has_history` (Plan 2B).
- Produces: `has_history` counts only `signed`, `active` and `completed` engagements. The profile-gap re-check applies only to first-time engagements; both paths still require completed onboarding.

This closes the Plan 3 roadmap row: "`has_history` counts unsigned in-flight engagements, which skews FR-5.3 first-time vs repeat metrics; reactivation also re-checks profile gaps."
- A worker whose only engagement is still unsigned has not yet worked with Bonarda, so another project engages them first-time.
- A returning worker (reactivation, FR-4.3's fast path) is not blocked for having removed a language. The original carry-forward targeted first-time engagements.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/engagements/test_engagement_paths.py`:

```python
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.enums import EngagementStatus
from tests.support import (
    bearer,
    engagement_terms,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

KEY = {"Idempotency-Key": "path-rules-0001"}


async def test_an_unsigned_engagement_is_not_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.AWAITING_SIGNATURE,
    )

    first_time = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )

    assert first_time.status_code == 201
    assert first_time.json()["path"] == "first_time"


async def test_an_unsigned_engagement_cannot_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
    )

    response = await client.post(
        f"/api/v1/workers/{worker.id}/reactivations",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm) | KEY,
    )

    assert (response.status_code, response.json()["code"]) == (409, "no_prior_engagement")


async def test_a_returning_worker_with_a_profile_gap_can_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], name="New")
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session, name="Old")).id
    )
    worker.languages = []
    await session.commit()

    response = await client.post(
        f"/api/v1/workers/{worker.id}/reactivations",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm) | KEY,
    )

    assert response.status_code == 201
    assert response.json()["path"] == "reactivation"


async def test_a_first_time_worker_with_a_profile_gap_is_still_not_ready(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    worker.languages = []
    await session.commit()

    response = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )

    assert (response.status_code, response.json()["code"]) == (409, "worker_not_ready")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/engagements/test_engagement_paths.py -v`
Expected:
- `test_an_unsigned_engagement_is_not_history` fails with 409 `use_reactivation`.
- `test_an_unsigned_engagement_cannot_be_reactivated` gets past the history check and fails on another code or status.
- The gap test fails with 409 `worker_not_ready`.

- [ ] **Step 3: Implement**

In `backend/app/modules/engagements/repository.py`, change `has_history` so its filter counts only work that has actually happened:

```python
_HISTORY_STATUSES = (
    EngagementStatus.SIGNED,
    EngagementStatus.ACTIVE,
    EngagementStatus.COMPLETED,
)
```

Declare `_HISTORY_STATUSES` at module level, and in `has_history` replace `Engagement.status != EngagementStatus.CANCELLED` with `Engagement.status.in_(_HISTORY_STATUSES)`. Update its docstring or comment: "Work that has actually happened: a signed contract or later (FR-5.3)."

In `backend/app/modules/engagements/engagements.py` `EngagementService.create`, change the readiness check to:

```python
        blocking_gaps = readiness.gaps if path is EngagementPath.FIRST_TIME else []
        if not readiness.onboarding_complete or blocking_gaps:
            missing = ", ".join(blocking_gaps) or "onboarding"
            raise Conflict(f"Worker profile incomplete: {missing}", code="worker_not_ready")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/engagements -v`
Expected: all pass. If an existing test relied on an unsigned engagement counting as history, it contradicts the rule this task sets. Update its setup to use a `signed` or `completed` engagement, and name the change in your report.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "fix(engagements): history means signed work; reactivation skips profile-gap check" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 8: End-to-end standing journey, roadmap and docs

**Files:**
- Create: `backend/tests/api/test_standing_journey.py`
- Modify: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`, `PROJECT_STRUCTURE.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the end-to-end test**

`backend/tests/api/test_standing_journey.py`:

```python
"""FR-2.2, FR-3.1–3.3, NFR-5.1: feedback from distinct reviewers raises a
worker's tier and verifies a skill; People Ops tighten the policy with two
people; the worker's standing explanation shows every step."""

import copy
from collections.abc import Awaitable, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.identity.models import UserAccount
from app.modules.passport.models import Skill
from tests.support import (
    POSITIVE_ANSWERS,
    _seed_policy_rows,
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def test_feedback_raises_standing_and_a_policy_change_is_explained(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)

    async def review(pm: UserAccount, name: str) -> None:
        project = await make_project(session, staff=[pm], name=name)
        engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
        response = await client.post(
            f"/api/v1/engagements/{engagement.id}/feedback",
            json={
                "structured_answers": POSITIVE_ANSWERS,
                "skill_ids_demonstrated": [str(skill.id)],
            },
            headers=bearer(settings, pm),
        )
        assert response.status_code == 201
        await drain()

    async def standing() -> dict[str, Any]:
        response = await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
        return response.json()

    # 1. One review: tier 1; the skill is not verified yet.
    await review(ama, "Volta")
    assert (await standing())["tier"] == "tier_1"

    # 2. Two more reviews from a second PM: tier 2 and a verified skill.
    await review(kwame, "Tema")
    await review(kwame, "Kumasi")
    after = await standing()
    assert after["tier"] == "tier_2"
    me = await client.get("/api/v1/workers/me", headers=bearer(settings, account))
    assert me.json()["skills"][0]["verification_status"] == "bonarda_verified"

    # 3. People Ops tighten tier 2 to four engagements; a second person activates.
    rules = copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering"))
    rules["tiers"][0]["min_completed"] = 4
    proposed = await client.post(
        "/api/v1/policies/tiering/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    self_activation = await client.post(
        "/api/v1/policies/tiering/versions/2/activate", headers=bearer(settings, author)
    )
    activated = await client.post(
        "/api/v1/policies/tiering/versions/2/activate", headers=bearer(settings, approver)
    )
    assert (proposed.status_code, self_activation.status_code, activated.status_code) == (
        201,
        403,
        200,
    )
    await drain()

    # 4. The worker drops to tier 1 under v2 and sees the whole history.
    final = await standing()
    assert (final["tier"], final["policy_version"]) == ("tier_1", 2)
    history = [(c["previous_tier"], c["new_tier"], c["policy_version"]) for c in final["history"]]
    # Newest first: the first review raised the tier on its own, the third
    # raised it again, and the v2 activation lowered it.
    assert history == [
        ("tier_2", "tier_1", 2),
        ("tier_1", "tier_2", 1),
        ("unrated", "tier_1", 1),
    ]
```

Run: `pytest tests/api/test_standing_journey.py -v`
Expected: PASS. If it fails, the failure shows an integration gap between tasks. Fix it in the owning module if the fix is small and obvious, and name it in your report.

- [ ] **Step 2: Update the roadmap**

In `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`, do the following.

**Plan table:**
- Replace the Plan 3 row with two rows:
  - `3A | 2026-09-25-bonarda-03a-standing.md | governance policies (versioned, two-person activation), standing (rules engine, append-only standing changes, skill evidence and verification, re-evaluation on activation and nightly, explanation API) | 2B | Written`
  - `3B | …-03b-roster.md | roster (read-model, scoring, candidates, first-shot, impression logging, first-shot visibility source) | 3A | Not written`
- Change Plan 4's "Depends on" to `3B`.

**Carry-forward:**
- Delete the row "`has_history` counts unsigned in-flight engagements…" (closed by Task 7).
- Add these rows:
  - `4` | Concentration and retention policy kinds have no rules schema yet; proposing one answers 400 `policy_kind_not_supported`.
  - `4` | An upheld dispute must set `feedback.excluded_from_standing` and recalculate the worker (spec §7.7 `DisputeResolved`).
  - `4` | Notify the worker when their standing changes (spec §7.7 `notify_worker` on `StandingChanged`).
  - `4` | Standing overrides (`POST /standing-overrides`) write `standing_changes` with `actor_id` and `override_reason`; the table already has both columns.
  - `any` | `recalculate_all` re-evaluates every worker in one transaction; batch it if the pool grows well past the pilot's 5,000 profiles.
  - `any` | Skill verification never reverses. Raising the policy threshold does not un-verify skills already verified.

**Deviations (Plan 3A rows):**
- The policy activation path is `POST /policies/{kind}/versions/{v}/activate`, not `:activate`. Reason: the same plain-REST convention as Plan 2B.
- `skill_evidence` is keyed by `(worker_id, skill_id, reviewer_id)`, not `skill_claim_id`. Reason: a self-reported claim can be deleted and re-added; evidence must neither block that nor be lost.
- Standing is also re-evaluated nightly at 03:00 UTC. Reason: tiers must fall when feedback ages out of the window, and no event fires for that.
- `standing_changes.actor_id` has no `ON DELETE SET NULL`. Reason: a cascading update would hit the append-only trigger; staff accounts are revoked, never deleted.
- `GET /workers/{id}/standing` (detail visibility) exists alongside `GET /workers/me/standing`. Reason: spec §7.1 gives detail viewers standing factors.
- Reactivation does not re-check profile gaps (location, languages, skills); first-time engagement does. Reason: FR-4.3's fast path for returning workers.

- [ ] **Step 3: Update PROJECT_STRUCTURE.md**

Under `modules/`, add after `engagements/`:

```
│   │   │   ├── governance/                # policy_configs, two-person activation (Plan 3A); disputes etc. Plan 4
│   │   │   │   ├── enums.py, models.py, repository.py, schemas.py
│   │   │   │   ├── policies.py, router.py
│   │   │   │   └── service.py
│   │   │   ├── standing/                  # tier rules engine, standing changes, skill evidence (Plan 3A)
│   │   │   │   ├── rules.py, models.py, repository.py, schemas.py
│   │   │   │   ├── recalculation.py, evidence.py, explanation.py
│   │   │   │   ├── handlers.py, router.py
│   │   │   │   └── service.py
```

Also add `queries.py` to the `engagements/` entry. Keep any existing placeholder lines for modules not yet built (`roster/`) as they are.

- [ ] **Step 4: Full verification**

Run from `backend/`: `ruff format --check . && ruff check . && mypy && lint-imports && pytest --cov=app --cov-report=term-missing`
Expected: all pass. Put the test count and TOTAL coverage in the commit body.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend docs PROJECT_STRUCTURE.md
git commit -m "test: end-to-end standing journey; record Plan 3A in roadmap and docs" -m "<test count and coverage>" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

## Spec coverage for this plan

| Spec / carry-forward item | Task |
|---|---|
| §6.1 `policy_configs` (unique kind+version, one active per kind, two-person check); seed tiering (§7.3) and matching (§7.4) v1 | 1 |
| §7.2 governance policy routes; NFR-5.1, NFR-9.2 two-person activation via API | 1 |
| FR-3.4 tier capped at 15% of the score; FR-6.2 no selection-frequency weight (enforced in `MatchingRules`) | 1 |
| §7.3 pure rules engine, window, positive ratio, first-met tier | 2 |
| §6.1 `standing_changes` append-only (§6.3 trigger), factors, policy version, trigger event; §6.4 index | 3 |
| §7.7 `FeedbackSubmitted` → `standing.recalculate`; `StandingChanged` event; §6.5 off the request path | 3 |
| FR-2.1, FR-2.2 skill evidence and distinct-reviewer verification; `SkillVerified` event | 4 |
| §7.7 `PolicyActivated(tiering)` → `standing.recalculate_all` | 5 |
| §2.1 #2, FR-1.3 `GET /workers/me/standing` explanation; §7.1 standing factors at detail | 6 |
| Carry-forward: `has_history` counting unsigned work; reactivation profile-gap friction | 7 |
| NFR-10.1 standing changed is an outbox event and an audit row | 3, 5 |

Deferred and recorded in Task 8:
- Plan 3B: the roster, including first-shot and candidate scoring against the matching policy seeded here, and the first-shot visibility source.
- Plan 4: dispute exclusion, overrides, standing notifications, and concentration and retention policy schemas.

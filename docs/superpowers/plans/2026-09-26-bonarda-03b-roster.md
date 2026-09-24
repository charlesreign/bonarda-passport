# Bonarda Plan 3B — Roster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `roster` module:
- a `roster_profiles` read-model kept current from events, with a nightly rebuild;
- candidate search scored against the active matching policy, with a `score_breakdown`;
- the first-shot panel, with impression logging and review outcomes;
- a first-shot visibility source.

It also closes the 3B carry-forward: the standing explanation reports the evaluated tier.

**Architecture:** Builds on Plans 1–3A (all merged to `main`).

`app/modules/roster/` never joins other modules' tables at query time (spec §5.2 rule 4). It keeps one `roster_profiles` row per worker:
- The row is rebuilt through `passport.service` and `engagements.service` read functions, whenever a worker-affecting event arrives.
- Every night, all rows are rebuilt to repair drift.

Scoring and first-shot selection are pure functions over roster rows and the active matching policy. The HTTP layer adds project context from `engagements.service` and records impressions.

Dependencies flow one way. `roster` imports `passport`, `engagements`, `standing`, `governance` and `identity` (all via `service`/`schemas`). No module imports `roster`, and a new import-linter contract enforces that.

**Tech Stack:** Python 3.12, FastAPI 0.115 (pinned), Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic, Arq, pytest + Testcontainers + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`. Relevant sections:
- §2.2 #2 (search needs a project context and returns summary cards)
- §5.1 and §5.2 (roster owns `roster_profiles` and `first_shot_reviews`; no cross-module joins)
- §6.1 (`roster_profiles`, `first_shot_reviews`)
- §6.4 (roster indexes)
- §6.5 (roster updates are eventual; nightly rebuild)
- §7.1 (the detail level includes a PM whose `first_shot_reviews` outcome is `shortlisted`, `contacted` or `engaged`)
- §7.2 (roster routes)
- §7.4 (scoring, first-shot pool, ranking, impression logging)
- §7.7 (roster handlers; nightly `roster_rebuild`)
- §8.5 (consent withdrawal removes a worker within one relay cycle)

Roadmap with carry-forward and deviations: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`.

## Global Constraints

- Work on branch `feat/roster`, created from `main` after Plan 3A's merge. Run all commands from `backend/` with the venv at `backend/.venv` activated (`source .venv/Scripts/activate` in Git Bash). Docker must be running (Testcontainers Postgres).
- All routes are under `/api/v1`. Errors are RFC 9457 `application/problem+json` with a stable `code` field.
- A module imports another module only through its `service` or `schemas` submodule.
  - `app/main.py`, `app/worker/` and `app/wiring.py` are the composition root and may import anything.
  - `app.core` imports no module.
  - `governance` imports no domain module except `identity`.
  - `passport` and `engagements` never import `standing` or `governance`.
  - No module imports `roster` (a new contract in Task 1).
- `roster` never queries another module's tables. It reads other modules only through their `service` functions.
- Every state change a person makes (a first-shot review) writes `write_audit(...)` on the request's `AsyncSession`. Audit rows about workers carry no contact data, no names and no free text.
- Candidate and first-shot responses are summary-level (spec §7.1): name, verified and self-reported skills, tier, availability, location and engagement count. They never include engagement history, feedback or contact data.
- Tier weight is capped by the matching policy (at most 15%). Selection frequency and engagement count carry no weight in the score (FR-3.4, FR-6.2). The first-shot pool is never filtered by tier.
- Lock order, recorded in the roadmap:
  - workers: `FOR NO KEY UPDATE`, in id order;
  - skill claims: `FOR UPDATE`, sorted by skill id;
  - roster refreshes: serialized per worker with a transaction-level advisory lock.
  - New code must not hold a lock of one kind while waiting on another in the reverse order.
- Integrity errors are mapped by constraint name via `app.core.db.errors.violated_constraint(exc)`. Any other integrity error is re-raised.
- Enum columns use `app.core.db.types.pg_enum`. In migrations:
  - Check-constraint names go through `op.f("ck_<table>_<name>")`.
  - Unique, foreign-key, primary-key and index names are plain strings.
- Datetimes are timezone-aware UTC (`app.core.time.utcnow()`). "Today" is `utcnow().date()`.
- Async tests: never call `session.expire_all()` and then `session.get(...)`. Use `await session.refresh(obj)`.
- Before every commit, run this from `backend/` with no path arguments; all of it must pass: `ruff format . && ruff check . && mypy && lint-imports && pytest`.
- Commit messages are multi-line: a subject, a blank line, then a `Co-Authored-By:` trailer naming the model that wrote the commit.

## Review Focus

1. **Consent withdrawal.** A worker in another region who withdraws `cross_region_matching` consent disappears from that project's candidates and first-shot panel after one relay cycle (spec §8.5). (Test in Task 3.)
2. **Tier never gates first-shot.** An unrated, underused, qualified worker appears on the first-shot panel. An unrated worker with full verified coverage outranks a tier-2 worker with only self-reported coverage. (Tests in Tasks 2 and 4.)
3. **Serving the panel is idempotent.** Serving the first-shot panel again never duplicates impression rows. It never moves a `shortlisted` worker back to `shown`. (Test in Task 4.)
4. **Detail comes from a live relationship.** A PM who shortlisted a worker gets detail visibility and loses it the moment their staffing ends. A `passed` review never grants detail. (Tests in Task 5.)
5. **Two refreshes of one worker at once.** An event handler and the nightly rebuild running together leave the roster row reflecting the latest committed state, not a stale snapshot. (Test in Task 1.)

---

## File Structure

```
backend/
  alembic/versions/0010_roster.py              roster_profiles (+ pg_trgm) (Task 1)
  alembic/versions/0011_first_shot.py          first_shot_reviews (Task 4)
  pyproject.toml                               + contract: no module imports roster (Task 1)
  app/
    models_registry.py, main.py, wiring.py     + roster models, router, handlers, visibility source
    worker/jobs.py, worker/settings.py         + nightly rebuild_roster at 02:00 (Task 1)
    modules/roster/
      __init__.py
      models.py                                RosterProfile (Task 1), FirstShotReview (Task 4)
      repository.py                            RosterRepository (Task 1, 3), FirstShotRepository (Task 4)
      refresh.py                               refresh_worker(), rebuild_all() (Task 1)
      scoring.py                               pure availability_fit(), score(), rank() (Task 2)
      schemas.py                               cards, breakdown, pages, panel, review schemas
      candidates.py                            candidate search + cursor (Task 3)
      first_shot.py                            pure select_panel() (Task 4); panel + review services (Tasks 4, 5)
      visibility.py                            first_shot_relationship() (Task 5)
      handlers.py, router.py, service.py
    modules/passport/queries.py, schemas.py, service.py        + RosterWorker, roster_snapshot, all_worker_ids
    modules/engagements/enums.py, repository.py                HISTORY_STATUSES made public (Task 1)
    modules/engagements/queries.py, schemas.py, service.py     + EngagementActivity, engagement_activity,
                                                                 engagement_worker_id, ProjectContext,
                                                                 staffed_project, staffed_project_ids
    modules/governance/policies.py, schemas.py, service.py     + MatchingPolicy, active_matching (Task 2)
    modules/standing/explanation.py, schemas.py                + evaluated_tier (Task 6)
  tests/support.py                                             make_project(starts_on=), refresh_roster()
  tests/…                                                      one file per task
docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md, PROJECT_STRUCTURE.md   (Task 7)
```

---

### Task 1: The roster read-model

**Files:**
- Create: `backend/app/modules/roster/__init__.py`, `models.py`, `repository.py`, `refresh.py`, `handlers.py`, `service.py`; `backend/alembic/versions/0010_roster.py`
- Modify: `backend/pyproject.toml`, `backend/app/modules/passport/schemas.py`, `queries.py`, `service.py`, `backend/app/modules/engagements/enums.py`, `repository.py`, `queries.py`, `schemas.py`, `service.py`, `backend/app/models_registry.py`, `backend/app/wiring.py`, `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`, `backend/tests/support.py`
- Test: `backend/tests/api/roster/__init__.py`, `backend/tests/api/roster/test_read_model.py`

**Interfaces:**
- Consumes: event classes. The first four carry the worker as `aggregate_id`. The next three carry a `worker_id` field. `ContractSigned` carries the engagement as `aggregate_id`.
  - `WorkerInvited`, `WorkerUpdated`, `ConsentChanged` (passport.schemas)
  - `StandingChanged`, `SkillVerified` (standing.schemas)
  - `EngagementActivated`, `EngagementCompleted`, `EngagementCancelled` (engagements.schemas)
  - `ContractSigned` (engagements.schemas)
- Produces:
  - `passport.schemas.RosterWorker(worker_id, display_name, status, onboarding_state, data_region, cross_region_ok, standing_tier, skill_ids, verified_skill_ids, base_location, availability_status, available_from)`.
  - `passport.queries.roster_snapshot(session, worker_id) -> RosterWorker | None` and `all_worker_ids(session) -> list[UUID]` (ordered by id). Both are exported from `passport.service`.
  - `engagements.enums.HISTORY_STATUSES` (signed, active, completed). The repository uses it instead of its private copy.
  - `engagements.schemas.EngagementActivity(total, last_12m, last_engaged_on)`.
  - `engagements.queries.engagement_activity(session, worker_id, today) -> EngagementActivity` and `engagement_worker_id(session, engagement_id) -> UUID | None`. Both are exported from `engagements.service`.
  - Model `RosterProfile`.
  - `RosterRepository(session)`: `get(worker_id)`, `upsert(values)`, `delete(worker_id)`.
  - `refresh.refresh_worker(session, worker_id) -> bool` and `refresh.rebuild_all(session) -> int`.
  - `roster.service` exports `rebuild_all`.
  - `handlers.register(registry)`: handlers `roster.refresh_worker:<event_type>`.
  - Arq cron `rebuild_roster`, nightly at 02:00.
  - Test helper `refresh_roster(session)`.

The row holds every worker, whatever their status. Queries filter by status, onboarding and region.

`skill_ids` is every claimed skill, and `verified_skill_ids` is its `bonarda_verified` subset. Self-reported skills are `skill_ids − verified_skill_ids`.

Engagement counts use the history statuses: signed, active or completed. The same rule decides history for reactivation.
- `engagements_last_12m` counts engagements whose `start_date` falls in the last 365 days.
- `last_engaged_on` is the latest `start_date`.

Status-like columns are stored as plain strings. The roster is a projection and does not share passport's DB enum types.

Each refresh takes a transaction-scoped advisory lock keyed on the worker. A concurrent refresh then waits and reads the state committed by the first refresh, instead of overwriting it with an older snapshot.

- [ ] **Step 1: Cross-module read functions**

In `backend/app/modules/engagements/enums.py`, append:

```python
# Work that has actually happened: a signed contract or later (FR-5.3). The
# same rule decides reactivation history and roster engagement counts.
HISTORY_STATUSES = (
    EngagementStatus.SIGNED,
    EngagementStatus.ACTIVE,
    EngagementStatus.COMPLETED,
)
```

In `backend/app/modules/engagements/repository.py`, delete the private `_HISTORY_STATUSES` tuple. Import `HISTORY_STATUSES` from `app.modules.engagements.enums` and use it in `has_history` and `latest_for_worker`.

Append to `backend/app/modules/engagements/schemas.py`:

```python
class EngagementActivity(BaseModel):
    """How much a worker has worked with Bonarda, for the roster (spec §6.1)."""

    total: int
    last_12m: int
    last_engaged_on: date | None
```

Append to `backend/app/modules/engagements/queries.py`. Add the imports `timedelta` from datetime, `func` from sqlalchemy, `HISTORY_STATUSES` and `EngagementActivity`:

```python
async def engagement_activity(
    session: AsyncSession, worker_id: UUID, today: date
) -> EngagementActivity:
    since = today - timedelta(days=365)
    total, last_12m, last_on = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Engagement.start_date >= since),
                func.max(Engagement.start_date),
            ).where(Engagement.worker_id == worker_id, Engagement.status.in_(HISTORY_STATUSES))
        )
    ).one()
    return EngagementActivity(total=total, last_12m=last_12m, last_engaged_on=last_on)


async def engagement_worker_id(session: AsyncSession, engagement_id: UUID) -> UUID | None:
    return await session.scalar(select(Engagement.worker_id).where(Engagement.id == engagement_id))
```

Export `engagement_activity` and `engagement_worker_id` from `backend/app/modules/engagements/service.py`.

Append to `backend/app/modules/passport/schemas.py`:

```python
class RosterWorker(BaseModel):
    """What the roster projects from a passport (spec §6.1 roster_profiles)."""

    worker_id: UUID
    display_name: str
    status: WorkerStatus
    onboarding_state: OnboardingState
    data_region: str
    cross_region_ok: bool
    standing_tier: StandingTier
    skill_ids: list[UUID]
    verified_skill_ids: list[UUID]
    base_location: str | None
    availability_status: AvailabilityStatus
    available_from: date | None
```

Append to `backend/app/modules/passport/queries.py`, importing `RosterWorker` if missing:

```python
async def roster_snapshot(session: AsyncSession, worker_id: UUID) -> RosterWorker | None:
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None:
        return None
    claims = [claim for claim, _ in await SkillClaimRepository(session).list_for_worker(worker_id)]
    consent = await ConsentRepository(session).get(worker_id, ConsentPurpose.CROSS_REGION_MATCHING)
    return RosterWorker(
        worker_id=worker.id,
        display_name=worker.full_name,
        status=worker.status,
        onboarding_state=worker.onboarding_state,
        data_region=worker.data_region,
        cross_region_ok=consent is not None and consent.granted,
        standing_tier=worker.standing_tier,
        skill_ids=sorted({c.skill_id for c in claims}, key=str),
        verified_skill_ids=sorted(
            {
                c.skill_id
                for c in claims
                if c.verification_status is VerificationStatus.BONARDA_VERIFIED
            },
            key=str,
        ),
        base_location=worker.base_location,
        availability_status=worker.availability_status,
        available_from=worker.available_from,
    )


async def all_worker_ids(session: AsyncSession) -> list[UUID]:
    return list((await session.scalars(select(Worker.id).order_by(Worker.id))).all())
```

Export `roster_snapshot` and `all_worker_ids` from `backend/app/modules/passport/service.py`.

- [ ] **Step 2: Model, migration and import contract**

`backend/app/modules/roster/__init__.py`: empty file.

`backend/app/modules/roster/models.py`:

```python
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class RosterProfile(Base):
    """One row per worker, maintained from events and rebuilt nightly
    (spec §5.2 rule 4, §6.1). Search reads only this table."""

    __tablename__ = "roster_profiles"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    onboarding_state: Mapped[str] = mapped_column(String(20), nullable=False)
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    cross_region_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    standing_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
    verified_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
    base_location: Mapped[str | None] = mapped_column(String(120))
    availability_status: Mapped[str] = mapped_column(String(20), nullable=False)
    available_from: Mapped[date | None] = mapped_column(Date)
    engagements_total: Mapped[int] = mapped_column(Integer, nullable=False)
    engagements_last_12m: Mapped[int] = mapped_column(Integer, nullable=False)
    last_engaged_on: Mapped[date | None] = mapped_column(Date)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_roster_profiles_skill_ids", "skill_ids", postgresql_using="gin"),
        Index(
            "ix_roster_profiles_verified_skill_ids", "verified_skill_ids", postgresql_using="gin"
        ),
        Index(
            "ix_roster_profiles_region_availability",
            "data_region",
            "availability_status",
            postgresql_where=text("status IN ('active','dormant')"),
        ),
        Index("ix_roster_profiles_engagements_last_12m", "engagements_last_12m"),
        Index(
            "ix_roster_profiles_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
    )
```

`backend/alembic/versions/0010_roster.py`:

```python
"""roster: roster_profiles read-model

Revision ID: 0010_roster
Revises: 0009_standing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_roster"
down_revision: str | None = "0009_standing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "roster_profiles",
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("onboarding_state", sa.String(20), nullable=False),
        sa.Column("data_region", sa.String(8), nullable=False),
        sa.Column("cross_region_ok", sa.Boolean(), nullable=False),
        sa.Column("standing_tier", sa.String(20), nullable=False),
        sa.Column(
            "skill_ids", postgresql.ARRAY(_UUID), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "verified_skill_ids",
            postgresql.ARRAY(_UUID),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("base_location", sa.String(120), nullable=True),
        sa.Column("availability_status", sa.String(20), nullable=False),
        sa.Column("available_from", sa.Date(), nullable=True),
        sa.Column("engagements_total", sa.Integer(), nullable=False),
        sa.Column("engagements_last_12m", sa.Integer(), nullable=False),
        sa.Column("last_engaged_on", sa.Date(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name="pk_roster_profiles"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_roster_profiles_worker_id", ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_roster_profiles_skill_ids", "roster_profiles", ["skill_ids"], postgresql_using="gin"
    )
    op.create_index(
        "ix_roster_profiles_verified_skill_ids",
        "roster_profiles",
        ["verified_skill_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_roster_profiles_region_availability",
        "roster_profiles",
        ["data_region", "availability_status"],
        postgresql_where=sa.text("status IN ('active','dormant')"),
    )
    op.create_index(
        "ix_roster_profiles_engagements_last_12m", "roster_profiles", ["engagements_last_12m"]
    )
    op.create_index(
        "ix_roster_profiles_display_name_trgm",
        "roster_profiles",
        ["display_name"],
        postgresql_using="gin",
        postgresql_ops={"display_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_table("roster_profiles")
    # pg_trgm stays installed: other objects may use it, and dropping an
    # extension is not a schema change this revision owns.
```

Add `from app.modules.roster import models as roster_models` to `backend/app/models_registry.py`, and add `"roster_models"` to its `__all__`.

In `backend/pyproject.toml`, add an import-linter contract in the existing style:

```toml
[[tool.importlinter.contracts]]
name = "no module imports roster"
type = "forbidden"
source_modules = [
    "app.modules.identity",
    "app.modules.passport",
    "app.modules.engagements",
    "app.modules.standing",
    "app.modules.governance",
    "app.modules.integrations",
]
forbidden_modules = ["app.modules.roster"]
```

Run `pytest tests/integration/test_migrations.py -v`.

Expected: all pass. `test_models_match_migrations` might report a difference on the trigram index. For example, Alembic may compare the `gin_trgm_ops` operator class differently from how the model declares it. If so, first check the model's `postgresql_ops` spelling. If the difference persists, remove the trigram index from both the model and the migration, and name the removal in your report. Name search still works through `ILIKE` on the pilot's 5,000 rows. Task 7 records that removal as a deviation.

- [ ] **Step 3: Write the failing tests**

Append to `backend/tests/support.py`:

```python
async def refresh_roster(session: AsyncSession) -> None:
    """Rebuilds every roster row, as the nightly job does."""
    from app.modules.roster.service import rebuild_all

    await rebuild_all(session)
    await session.commit()
```

Import `rebuild_all` at the top of `tests/support.py` alongside the other `app` imports, unless that creates an import cycle. If it does, keep the local import and note why in a comment.

`backend/tests/api/roster/__init__.py`: empty file.

`backend/tests/api/roster/test_read_model.py`:

```python
import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim, Worker
from app.modules.passport.schemas import RosterWorker
from app.modules.roster import refresh as refresh_module
from app.modules.roster.models import RosterProfile
from app.modules.roster.refresh import refresh_worker
from tests.support import (
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


async def _profile(session: AsyncSession, worker: Worker) -> RosterProfile:
    profile = await session.get(RosterProfile, worker.id)
    assert profile is not None
    await session.refresh(profile)
    return profile


async def test_invited_workers_appear_after_the_relay_runs(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    response = await client.post(
        "/api/v1/workers/invitations",
        json={
            "email": "kofi@example.com",
            "full_name": "Kofi Mensah",
            "worker_type": "freelancer",
            "data_region": "GH",
        },
        headers=bearer(settings, pm),
    )

    await drain()

    profile = await session.get(RosterProfile, response.json()["worker_id"])
    assert profile is not None
    assert (profile.display_name, profile.status, profile.onboarding_state) == (
        "Kofi Mensah",
        "dormant",
        "invited",
    )


async def test_the_row_projects_skills_and_signed_engagement_counts(
    session: AsyncSession,
) -> None:
    worker, _ = await make_ready_worker(session)
    project = await make_project(session)
    today = utcnow().date()
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, start_date=today - timedelta(days=30)
    )
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, start_date=today - timedelta(days=400)
    )
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Pending")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
        start_date=today,
    )
    python = Skill(slug="python", name_i18n={"en": "Python"})
    session.add(python)
    await session.flush()
    session.add(
        SkillClaim(
            worker_id=worker.id,
            skill_id=python.id,
            verification_status=VerificationStatus.BONARDA_VERIFIED,
        )
    )
    await session.commit()

    await refresh_roster(session)

    profile = await _profile(session, worker)
    assert set(profile.skill_ids) == {
        s.id for s in (await session.scalars(select(Skill))).all()
    }
    assert profile.verified_skill_ids == [python.id]
    assert (profile.engagements_total, profile.engagements_last_12m) == (2, 1)
    assert profile.last_engaged_on == today - timedelta(days=30)
    assert (profile.base_location, profile.availability_status) == ("Accra", "available")


async def test_profile_edits_reach_the_roster_through_events(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    await refresh_roster(session)

    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "unavailable"},
        headers=bearer(settings, account),
    )
    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=bearer(settings, account),
    )
    await drain()

    profile = await _profile(session, worker)
    assert (profile.availability_status, profile.cross_region_ok) == ("unavailable", True)


async def test_the_nightly_rebuild_repairs_drift(session: AsyncSession) -> None:
    worker, _ = await make_ready_worker(session)
    await refresh_roster(session)
    await session.execute(
        update(RosterProfile)
        .where(RosterProfile.worker_id == worker.id)
        .values(display_name="Stale", standing_tier="tier_2")
    )
    await session.commit()

    await refresh_roster(session)

    profile = await _profile(session, worker)
    assert (profile.display_name, profile.standing_tier) == ("Kofi Mensah", "unrated")


async def test_concurrent_refreshes_keep_the_latest_committed_state(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow refresh that read an old snapshot must not commit it after a newer
    refresh. Without the per-worker advisory lock, the second refresh finishes
    first and the slow one overwrites it with the stale name."""
    worker, _ = await make_ready_worker(session)
    real_snapshot = refresh_module.roster_snapshot
    first_has_read = asyncio.Event()
    second_done = asyncio.Event()
    calls = 0

    async def slow_snapshot(s: AsyncSession, worker_id: UUID) -> RosterWorker | None:
        nonlocal calls
        calls += 1
        snapshot = await real_snapshot(s, worker_id)
        if calls == 1:
            first_has_read.set()
            try:
                # With the lock the second refresh is blocked, so this times out.
                await asyncio.wait_for(second_done.wait(), timeout=1)
            except TimeoutError:
                pass
        return snapshot

    monkeypatch.setattr(refresh_module, "roster_snapshot", slow_snapshot)

    async def first() -> None:
        async with sessionmaker() as s, s.begin():
            await refresh_worker(s, worker.id)

    async def second() -> None:
        await first_has_read.wait()
        async with sessionmaker() as s, s.begin():
            await s.execute(
                update(Worker).where(Worker.id == worker.id).values(full_name="Kofi A. Mensah")
            )
        async with sessionmaker() as s, s.begin():
            await refresh_worker(s, worker.id)
        second_done.set()

    await asyncio.wait_for(asyncio.gather(first(), second()), timeout=15)

    assert (await _profile(session, worker)).display_name == "Kofi A. Mensah"
```

Adjust the payload keys of the consent PUT to match the existing consent tests in `tests/api/passport/`. `ConsentUpdate` has only `granted`. If `PUT /workers/me/consents/{purpose}` needs anything else, follow those tests.

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/api/roster -v`
Expected: FAIL. You should see `ModuleNotFoundError: No module named 'app.modules.roster.refresh'`.

- [ ] **Step 5: Implement**

`backend/app/modules/roster/repository.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roster.models import RosterProfile


class RosterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, worker_id: UUID) -> RosterProfile | None:
        return await self.session.get(RosterProfile, worker_id)

    async def upsert(self, values: dict[str, Any]) -> None:
        changes = {k: v for k, v in values.items() if k != "worker_id"}
        await self.session.execute(
            pg_insert(RosterProfile)
            .values(**values)
            .on_conflict_do_update(index_elements=[RosterProfile.worker_id], set_=changes)
        )

    async def delete(self, worker_id: UUID) -> None:
        await self.session.execute(delete(RosterProfile).where(RosterProfile.worker_id == worker_id))
```

`backend/app/modules/roster/refresh.py`:

```python
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.engagements.service import engagement_activity
from app.modules.passport.service import all_worker_ids, roster_snapshot
from app.modules.roster.repository import RosterRepository


async def _lock_worker_refresh(session: AsyncSession, worker_id: UUID) -> None:
    """Serializes refreshes of one worker for the rest of the transaction, so
    a slower refresh never overwrites a newer snapshot with an older one."""
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(worker_id), 0)))
    )


async def refresh_worker(session: AsyncSession, worker_id: UUID) -> bool:
    """Rebuilds one roster row from its sources. Returns False if the worker
    no longer exists (the row is removed)."""
    await _lock_worker_refresh(session, worker_id)
    repo = RosterRepository(session)
    snapshot = await roster_snapshot(session, worker_id)
    if snapshot is None:
        await repo.delete(worker_id)
        return False
    activity = await engagement_activity(session, worker_id, utcnow().date())
    await repo.upsert(
        {
            "worker_id": snapshot.worker_id,
            "display_name": snapshot.display_name,
            "status": snapshot.status.value,
            "onboarding_state": snapshot.onboarding_state.value,
            "data_region": snapshot.data_region,
            "cross_region_ok": snapshot.cross_region_ok,
            "standing_tier": snapshot.standing_tier.value,
            "skill_ids": snapshot.skill_ids,
            "verified_skill_ids": snapshot.verified_skill_ids,
            "base_location": snapshot.base_location,
            "availability_status": snapshot.availability_status.value,
            "available_from": snapshot.available_from,
            "engagements_total": activity.total,
            "engagements_last_12m": activity.last_12m,
            "last_engaged_on": activity.last_engaged_on,
            "refreshed_at": utcnow(),
        }
    )
    return True


async def rebuild_all(session: AsyncSession) -> int:
    """Nightly drift repair (spec §6.5). Workers are visited in id order."""
    worker_ids = await all_worker_ids(session)
    for worker_id in worker_ids:
        await refresh_worker(session, worker_id)
    return len(worker_ids)
```

`refresh_worker` calls `roster_snapshot` through the module-level name imported in `refresh.py`, which the concurrency test monkeypatches. Keep the import as `from app.modules.passport.service import all_worker_ids, roster_snapshot` so the patch takes effect.

`backend/app/modules/roster/handlers.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.events import DomainEvent
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.schemas import (
    ContractSigned,
    EngagementActivated,
    EngagementCancelled,
    EngagementCompleted,
)
from app.modules.engagements.service import engagement_worker_id
from app.modules.passport.schemas import ConsentChanged, WorkerInvited, WorkerUpdated
from app.modules.roster.refresh import refresh_worker
from app.modules.standing.schemas import SkillVerified, StandingChanged

# aggregate_id is the worker.
_WORKER_EVENTS: tuple[type[DomainEvent], ...] = (
    WorkerInvited,
    WorkerUpdated,
    ConsentChanged,
    StandingChanged,
    SkillVerified,
)
# The payload carries worker_id.
_ENGAGEMENT_EVENTS: tuple[type[DomainEvent], ...] = (
    EngagementActivated,
    EngagementCompleted,
    EngagementCancelled,
)


def register(registry: HandlerRegistry) -> None:
    async def by_aggregate(session: AsyncSession, payload: dict[str, Any]) -> None:
        await refresh_worker(session, UUID(payload["aggregate_id"]))

    async def by_worker_field(session: AsyncSession, payload: dict[str, Any]) -> None:
        await refresh_worker(session, UUID(payload["worker_id"]))

    async def by_engagement(session: AsyncSession, payload: dict[str, Any]) -> None:
        worker_id = await engagement_worker_id(session, UUID(payload["aggregate_id"]))
        if worker_id is not None:
            await refresh_worker(session, worker_id)

    for event in _WORKER_EVENTS:
        registry.register(event, f"roster.refresh_worker:{event.event_type}", by_aggregate)
    for event in _ENGAGEMENT_EVENTS:
        registry.register(event, f"roster.refresh_worker:{event.event_type}", by_worker_field)
    registry.register(
        ContractSigned, f"roster.refresh_worker:{ContractSigned.event_type}", by_engagement
    )
```

`backend/app/modules/roster/service.py`:

```python
"""Public interface of the roster module. No other module imports it."""

from app.modules.roster.refresh import rebuild_all

__all__ = ["rebuild_all"]
```

In `backend/app/wiring.py`, import `from app.modules.roster import handlers as roster_handlers` and call `roster_handlers.register(registry)` after the standing registration.

Append to `backend/app/worker/jobs.py`, importing `rebuild_all` from `app.modules.roster.service`:

```python
async def rebuild_roster(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await rebuild_all(session)
```

In `backend/app/worker/settings.py`, import it and add `cron(rebuild_roster, hour={2}, minute={0})` to `cron_jobs`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/api/roster tests/integration/test_migrations.py tests/api/engagements -v`
Expected: all pass. Also run `lint-imports` and confirm the new contract is listed as kept.

- [ ] **Step 7: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests pyproject.toml
git commit -m "feat(roster): roster_profiles read-model from events with nightly rebuild" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 2: The matching policy and the scoring engine

**Files:**
- Create: `backend/app/modules/roster/scoring.py`, `backend/app/modules/roster/schemas.py`
- Modify: `backend/app/modules/governance/schemas.py`, `policies.py`, `service.py`
- Test: `backend/tests/unit/roster/__init__.py`, `backend/tests/unit/roster/test_scoring.py`, `backend/tests/api/governance/test_active_matching.py`

**Interfaces:**
- Consumes: `MatchingRules` (governance.schemas), and the seeded matching v1 policy (weights 0.5/0.2/0.15/0.15; tier weights unrated 0, tier_1 0.5, tier_2 1; `availability_near_days` 14).
- Produces:
  - `governance.schemas.MatchingPolicy(id, version, rules: MatchingRules)`.
  - `governance.policies.active_matching(session) -> MatchingPolicy`, exported from `governance.service`.
  - `roster.schemas.ScoreComponent(weight, value, points)` and `ScoreBreakdown(verified_skills, self_reported_skills, availability, tier, total, policy_version)`.
  - In `roster.scoring`:
    - `ProjectNeeds(required_skill_ids: frozenset[UUID], starts_on: date)`
    - `availability_fit(status, available_from, starts_on, near_days) -> float`
    - `score(profile, needs, policy) -> ScoreBreakdown`
    - `rank(profiles, needs, policy) -> list[tuple[ScoreBreakdown, RosterProfile]]`, which sorts by total descending, then by worker id.

Scoring rules (spec §7.4), with required skills *S*:
- `value(verified) = |verified ∩ S| / |S|`.
- `value(self_reported) = |(claimed − verified) ∩ S| / |S|`.
- Both skill values are 0 when *S* is empty.
- `availability_fit`:
  - 1 if `available`;
  - 1 if `available_from` on or before the project start;
  - 0.5 if `available_from` within `availability_near_days` after the start;
  - otherwise 0 (including `unavailable`).
- The tier value comes from `tier_weights`.
- `points = weight × value`, rounded to 4 places. `total` is the rounded sum.
- The function takes no engagement count and no selection history, so neither can influence the score.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/roster/__init__.py`: empty file.

`backend/tests/unit/roster/test_scoring.py`:

```python
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.governance.schemas import MatchingPolicy, MatchingRules
from app.modules.roster.models import RosterProfile
from app.modules.roster.scoring import ProjectNeeds, availability_fit, rank, score
from tests.support import _seed_policy_rows

START = date(2026, 10, 1)
POLICY = MatchingPolicy(
    id=uuid4(),
    version=1,
    rules=MatchingRules.model_validate(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    ),
)


def _profile(
    *,
    claimed: list[UUID] | None = None,
    verified: list[UUID] | None = None,
    tier: str = "unrated",
    availability: str = "available",
    available_from: date | None = None,
    engagements_last_12m: int = 0,
) -> RosterProfile:
    return RosterProfile(
        worker_id=uuid4(),
        display_name="Test",
        status="dormant",
        onboarding_state="profile_complete",
        data_region="GH",
        cross_region_ok=False,
        standing_tier=tier,
        skill_ids=list(claimed or []),
        verified_skill_ids=list(verified or []),
        base_location="Accra",
        availability_status=availability,
        available_from=available_from,
        engagements_total=engagements_last_12m,
        engagements_last_12m=engagements_last_12m,
        last_engaged_on=None,
        refreshed_at=None,
    )


@pytest.mark.parametrize(
    ("status", "available_from", "fit"),
    [
        ("available", None, 1.0),
        ("available_from", START, 1.0),
        ("available_from", START + timedelta(days=14), 0.5),
        ("available_from", START + timedelta(days=15), 0.0),
        ("available_from", None, 0.0),
        ("unavailable", None, 0.0),
    ],
)
def test_availability_fit(status: str, available_from: date | None, fit: float) -> None:
    assert availability_fit(status, available_from, START, 14) == fit


def test_verified_and_self_reported_coverage_are_weighted_separately() -> None:
    a, b = uuid4(), uuid4()
    needs = ProjectNeeds(required_skill_ids=frozenset({a, b}), starts_on=START)

    breakdown = score(_profile(claimed=[a, b], verified=[a]), needs, POLICY)

    assert (breakdown.verified_skills.value, breakdown.verified_skills.points) == (0.5, 0.25)
    assert (breakdown.self_reported_skills.value, breakdown.self_reported_skills.points) == (
        0.5,
        0.1,
    )
    assert breakdown.availability.points == 0.15
    assert breakdown.tier.points == 0.0
    assert breakdown.total == 0.5
    assert breakdown.policy_version == 1


def test_tier_cannot_outweigh_verified_skills() -> None:
    skill = uuid4()
    needs = ProjectNeeds(required_skill_ids=frozenset({skill}), starts_on=START)
    verified_unrated = _profile(claimed=[skill], verified=[skill])
    self_reported_trusted = _profile(claimed=[skill], tier="tier_2")

    ranked = rank([self_reported_trusted, verified_unrated], needs, POLICY)

    assert ranked[0][1] is verified_unrated
    assert ranked[0][0].total == 0.65
    assert ranked[1][0].total == 0.5


def test_engagement_count_has_no_weight() -> None:
    skill = uuid4()
    needs = ProjectNeeds(required_skill_ids=frozenset({skill}), starts_on=START)

    busy = score(_profile(claimed=[skill], engagements_last_12m=9), needs, POLICY)
    idle = score(_profile(claimed=[skill], engagements_last_12m=0), needs, POLICY)

    assert busy.total == idle.total


def test_a_project_without_required_skills_scores_availability_and_tier_only() -> None:
    needs = ProjectNeeds(required_skill_ids=frozenset(), starts_on=START)

    breakdown = score(_profile(tier="tier_1"), needs, POLICY)

    assert (breakdown.verified_skills.value, breakdown.self_reported_skills.value) == (0.0, 0.0)
    assert breakdown.total == 0.225


def test_ranking_ties_break_on_worker_id() -> None:
    needs = ProjectNeeds(required_skill_ids=frozenset(), starts_on=START)
    profiles = [_profile(), _profile(), _profile()]

    ranked = rank(profiles, needs, POLICY)

    assert [p.worker_id for _, p in ranked] == sorted((p.worker_id for p in profiles), key=str)
```

`backend/tests/api/governance/test_active_matching.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.governance.service import active_matching


async def test_the_seeded_matching_policy_is_active(session: AsyncSession) -> None:
    policy = await active_matching(session)

    assert policy.version == 1
    assert policy.rules.weights.tier == 0.15
    assert policy.rules.first_shot.panel_size == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/roster tests/api/governance/test_active_matching.py -v`
Expected: FAIL with `ImportError: cannot import name 'MatchingPolicy'`.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/governance/schemas.py`:

```python
class MatchingPolicy(BaseModel):
    id: UUID
    version: int
    rules: MatchingRules
```

Append to `backend/app/modules/governance/policies.py` (import `MatchingPolicy`, `MatchingRules`):

```python
async def active_matching(session: AsyncSession) -> MatchingPolicy:
    policy = await PolicyRepository(session).active(PolicyKind.MATCHING)
    if policy is None:
        raise RuntimeError("no active matching policy; migration 0008 seeds one")
    return MatchingPolicy(
        id=policy.id, version=policy.version, rules=MatchingRules.model_validate(policy.rules)
    )
```

Export `active_matching` from `backend/app/modules/governance/service.py`.

`backend/app/modules/roster/schemas.py`:

```python
from pydantic import BaseModel


class ScoreComponent(BaseModel):
    weight: float
    value: float
    points: float


class ScoreBreakdown(BaseModel):
    """Every candidate carries how its score was made (spec §7.4)."""

    verified_skills: ScoreComponent
    self_reported_skills: ScoreComponent
    availability: ScoreComponent
    tier: ScoreComponent
    total: float
    policy_version: int
```

`backend/app/modules/roster/scoring.py`:

```python
"""Candidate scoring (spec §7.4, FR-3.4, FR-6.1, FR-6.2): pure functions over
roster rows and the active matching policy. Engagement count and selection
history are not inputs, so they cannot influence the score."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.modules.governance.schemas import MatchingPolicy
from app.modules.roster.models import RosterProfile
from app.modules.roster.schemas import ScoreBreakdown, ScoreComponent


@dataclass(frozen=True, slots=True)
class ProjectNeeds:
    required_skill_ids: frozenset[UUID]
    starts_on: date


def availability_fit(
    status: str, available_from: date | None, starts_on: date, near_days: int
) -> float:
    if status == "available":
        return 1.0
    if status == "available_from" and available_from is not None:
        if available_from <= starts_on:
            return 1.0
        if available_from <= starts_on + timedelta(days=near_days):
            return 0.5
    return 0.0


def _component(weight: float, value: float) -> ScoreComponent:
    return ScoreComponent(weight=weight, value=round(value, 4), points=round(weight * value, 4))


def score(profile: RosterProfile, needs: ProjectNeeds, policy: MatchingPolicy) -> ScoreBreakdown:
    rules = policy.rules
    required = needs.required_skill_ids
    verified = set(profile.verified_skill_ids)
    self_reported = set(profile.skill_ids) - verified
    verified_value = len(required & verified) / len(required) if required else 0.0
    self_value = len(required & self_reported) / len(required) if required else 0.0
    fit = availability_fit(
        profile.availability_status,
        profile.available_from,
        needs.starts_on,
        rules.availability_near_days,
    )
    parts = {
        "verified_skills": _component(rules.weights.verified_skills, verified_value),
        "self_reported_skills": _component(rules.weights.self_reported_skills, self_value),
        "availability": _component(rules.weights.availability, fit),
        "tier": _component(rules.weights.tier, rules.tier_weights[profile.standing_tier]),
    }
    return ScoreBreakdown(
        **parts,
        total=round(sum(c.points for c in parts.values()), 4),
        policy_version=policy.version,
    )


def rank(
    profiles: Iterable[RosterProfile], needs: ProjectNeeds, policy: MatchingPolicy
) -> list[tuple[ScoreBreakdown, RosterProfile]]:
    scored = [(score(p, needs, policy), p) for p in profiles]
    return sorted(scored, key=lambda sp: (-sp[0].total, str(sp[1].worker_id)))
```

`rules.tier_weights[...]` is keyed by `Literal["unrated", "tier_1", "tier_2"]`, while `standing_tier` is a `str`. If mypy rejects the lookup, cast the key with `typing.cast` to the literal type. Do not widen the governance schema.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/roster tests/api/governance -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(roster): matching policy and candidate scoring engine" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 3: Candidate search

**Files:**
- Create: `backend/app/modules/roster/candidates.py`, `backend/app/modules/roster/router.py`
- Modify: `backend/app/modules/roster/repository.py`, `backend/app/modules/roster/schemas.py`, `backend/app/modules/engagements/schemas.py`, `queries.py`, `service.py`, `backend/app/main.py`, `backend/tests/support.py`
- Test: `backend/tests/api/roster/test_candidates.py`

**Interfaces:**
- Consumes:
  - `rank`, `ProjectNeeds` and `score` (Task 2)
  - `active_matching` (Task 2)
  - `RosterProfile` and `RosterRepository` (Task 1)
  - `Permission.ROSTER_SEARCH` (PM only)
- Produces:
  - `engagements.schemas.ProjectContext(id, name, data_region, required_skill_ids, starts_on, status)`.
  - `engagements.queries.staffed_project(session, user_id, project_id) -> ProjectContext | None` and `staffed_project_ids(session, user_id) -> list[UUID]`. Both are exported from `engagements.service`.
  - `RosterRepository.eligible(data_region, *, skill_ids=(), availability=None, location=None, q=None) -> list[RosterProfile]`. It returns workers who are `active` or `dormant` and `profile_complete`, and who are in the region or have `cross_region_ok`.
  - `roster.schemas.CandidateCard`, `Candidate`, `CandidatePage`.
  - `candidates.project_needs(project, today) -> ProjectNeeds`.
  - `candidates.search(session, actor, project_id, filters, cursor, limit) -> CandidatePage`.
  - `candidates.card(profile) -> CandidateCard`.
  - Route `GET /api/v1/projects/{project_id}/candidates`, with query parameters `skill_ids`, `availability`, `location`, `q`, `cursor` and `limit`. `limit` defaults to 25, with a maximum of 100.
  - Error codes: `project_not_found` (404) and `invalid_cursor` (400).
  - Test helper: `make_project(..., starts_on=None)`.

The project start is `max(project.starts_on or today, today)`, because a project that has already started needs people now.

Candidates are sorted by total score, highest first, with ties broken by worker id. The cursor is an opaque token holding the last item's `(total, worker_id)`. It is keyset pagination over the computed ordering. The whole eligible pool is scored per request, which is fine for the pilot's 5,000 profiles; Task 7 records it as a carry-forward. `location` and `q` match case-insensitively, and `%` and `_` in them are literal characters.

- [ ] **Step 1: Write the failing tests**

Add a keyword parameter `starts_on: date | None = None` to `make_project` in `backend/tests/support.py` and pass it through to `Project(...)`.

`backend/tests/api/roster/test_candidates.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.passport.enums import (
    AvailabilityStatus,
    OnboardingState,
    VerificationStatus,
    WorkerStatus,
)
from app.modules.passport.models import Skill, SkillClaim
from tests.support import (
    bearer,
    make_project,
    make_ready_worker,
    make_user,
    make_worker,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


def _url(project_id: object) -> str:
    return f"/api/v1/projects/{project_id}/candidates"


async def _skill(session: AsyncSession) -> Skill:
    return (await session.scalars(select(Skill).where(Skill.slug == "data-analysis"))).one()


async def _verify(session: AsyncSession, worker_id: object, skill: Skill) -> None:
    claim = (
        await session.scalars(
            select(SkillClaim).where(
                SkillClaim.worker_id == worker_id, SkillClaim.skill_id == skill.id
            )
        )
    ).one()
    claim.verification_status = VerificationStatus.BONARDA_VERIFIED
    await session.commit()


async def test_candidates_are_region_eligible_scored_and_summary_only(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    kofi, _ = await make_ready_worker(session, email="kofi@example.com", full_name="Kofi")
    skill = await _skill(session)
    project = await make_project(session, staff=[pm], required_skill_ids=[skill.id])
    ama, _ = await make_ready_worker(session, email="ama@example.com", full_name="Ama")
    await _verify(session, ama.id, skill)
    lea, _ = await make_ready_worker(
        session, email="lea@example.com", full_name="Léa", data_region="EU"
    )
    await make_worker(
        session, email="new@example.com", onboarding_state=OnboardingState.INVITED
    )
    await make_worker(session, email="gone@example.com", status=WorkerStatus.ANONYMIZED)
    await refresh_roster(session)

    response = await client.get(_url(project.id), headers=bearer(settings, pm))

    body = response.json()
    assert response.status_code == 200
    assert [c["worker"]["display_name"] for c in body["items"]] == ["Ama", "Kofi"]
    top = body["items"][0]
    assert top["score"] == 0.65
    assert top["score_breakdown"]["verified_skills"]["points"] == 0.5
    assert top["score_breakdown"]["policy_version"] == 1
    assert set(top["worker"]) == {
        "worker_id",
        "display_name",
        "standing_tier",
        "verified_skill_ids",
        "self_reported_skill_ids",
        "availability_status",
        "available_from",
        "base_location",
        "engagements_total",
    }
    assert body["next_cursor"] is None
    assert str(lea.id) not in {c["worker"]["worker_id"] for c in body["items"]}


async def test_withdrawing_cross_region_consent_removes_a_candidate(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="EU")
    worker, account = await make_ready_worker(session, data_region="GH")
    worker_headers = bearer(settings, account)
    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=worker_headers,
    )
    await drain()
    with_consent = await client.get(_url(project.id), headers=bearer(settings, pm))

    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": False},
        headers=worker_headers,
    )
    await drain()
    without_consent = await client.get(_url(project.id), headers=bearer(settings, pm))

    assert [c["worker"]["worker_id"] for c in with_consent.json()["items"]] == [str(worker.id)]
    assert without_consent.json()["items"] == []


async def test_filters_narrow_the_pool(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    await make_ready_worker(session, email="kofi@example.com", full_name="Kofi 100%")
    ama, _ = await make_ready_worker(session, email="ama@example.com", full_name="Ama")
    ama.base_location = "Kumasi"
    ama.availability_status = AvailabilityStatus.UNAVAILABLE
    await session.commit()
    python = Skill(slug="python", name_i18n={"en": "Python"})
    session.add(python)
    await session.flush()
    session.add(SkillClaim(worker_id=ama.id, skill_id=python.id))
    await session.commit()
    await refresh_roster(session)
    headers = bearer(settings, pm)

    async def names(**params: object) -> list[str]:
        response = await client.get(_url(project.id), params=params, headers=headers)
        return [c["worker"]["display_name"] for c in response.json()["items"]]

    assert await names(skill_ids=str(python.id)) == ["Ama"]
    assert await names(location="kumasi") == ["Ama"]
    assert await names(availability="unavailable") == ["Ama"]
    assert await names(q="100%") == ["Kofi 100%"]
    assert await names(q="%") == ["Kofi 100%"]


async def test_the_cursor_walks_every_candidate_once(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(
        session, staff=[pm], starts_on=utcnow().date() + timedelta(days=7)
    )
    for i in range(5):
        await make_ready_worker(session, email=f"w{i}@example.com", full_name=f"Worker {i}")
    await refresh_roster(session)
    headers = bearer(settings, pm)

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params: dict[str, object] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get(_url(project.id), params=params, headers=headers)).json()
        seen += [c["worker"]["worker_id"] for c in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_bad_cursor_unstaffed_pm_and_other_roles(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    outsider = await make_user(session, role=UserRole.PM)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    project = await make_project(session, staff=[pm])

    bad = await client.get(
        _url(project.id), params={"cursor": "not-a-cursor"}, headers=bearer(settings, pm)
    )
    unstaffed = await client.get(_url(project.id), headers=bearer(settings, outsider))
    people_ops = await client.get(_url(project.id), headers=bearer(settings, ops))

    assert (bad.status_code, bad.json()["code"]) == (400, "invalid_cursor")
    assert (unstaffed.status_code, unstaffed.json()["code"]) == (404, "project_not_found")
    assert people_ops.status_code == 403
```

`make_ready_worker` gives every worker the `data-analysis` claim. In the first test, both GH workers claim the required skill: Ama has it verified (0.5 + 0.15 = 0.65), and Kofi has it self-reported (0.2 + 0.15 = 0.35).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/roster/test_candidates.py -v`
Expected: FAIL, because `/api/v1/projects/{id}/candidates` returns 404: there is no route yet.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/engagements/schemas.py`:

```python
class ProjectContext(BaseModel):
    """A project as other modules may see it."""

    id: UUID
    name: str
    data_region: str
    required_skill_ids: list[UUID]
    starts_on: date | None
    status: ProjectStatus
```

Append to `backend/app/modules/engagements/queries.py`, importing `ProjectRepository` and `ProjectContext`:

```python
async def staffed_project(
    session: AsyncSession, user_id: UUID, project_id: UUID
) -> ProjectContext | None:
    """The project, if this user actively staffs it as an active PM."""
    projects = ProjectRepository(session)
    project = await projects.get(project_id)
    if project is None or not await projects.is_staffed(project.id, user_id):
        return None
    return ProjectContext(
        id=project.id,
        name=project.name,
        data_region=project.data_region,
        required_skill_ids=project.required_skill_ids,
        starts_on=project.starts_on,
        status=project.status,
    )


async def staffed_project_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    return [p.id for p in await ProjectRepository(session).list_staffed_by(user_id)]
```

Export both from `backend/app/modules/engagements/service.py`.

Append to `RosterRepository` in `backend/app/modules/roster/repository.py` (imports: `Sequence`, `or_`, `select`):

```python
    async def eligible(
        self,
        data_region: str,
        *,
        skill_ids: Sequence[UUID] = (),
        availability: str | None = None,
        location: str | None = None,
        q: str | None = None,
    ) -> list[RosterProfile]:
        """Summary-eligible workers for a project in `data_region` (spec §7.1,
        §8.5): in the talent pool, onboarded, and in the region or consented."""
        stmt = select(RosterProfile).where(
            RosterProfile.status.in_(("active", "dormant")),
            RosterProfile.onboarding_state == "profile_complete",
            or_(
                RosterProfile.data_region == data_region,
                RosterProfile.cross_region_ok.is_(True),
            ),
        )
        if skill_ids:
            stmt = stmt.where(RosterProfile.skill_ids.contains(list(skill_ids)))
        if availability is not None:
            stmt = stmt.where(RosterProfile.availability_status == availability)
        if location:
            stmt = stmt.where(RosterProfile.base_location.icontains(location, autoescape=True))
        if q:
            stmt = stmt.where(RosterProfile.display_name.icontains(q, autoescape=True))
        return list((await self.session.scalars(stmt)).all())
```

Append to `backend/app/modules/roster/schemas.py` (imports: `date`, `UUID`):

```python
class CandidateCard(BaseModel):
    """Summary level only (spec §7.1): no history, feedback or contact data."""

    worker_id: UUID
    display_name: str
    standing_tier: str
    verified_skill_ids: list[UUID]
    self_reported_skill_ids: list[UUID]
    availability_status: str
    available_from: date | None
    base_location: str | None
    engagements_total: int


class Candidate(BaseModel):
    worker: CandidateCard
    score: float
    score_breakdown: ScoreBreakdown


class CandidatePage(BaseModel):
    items: list[Candidate]
    next_cursor: str | None
```

`backend/app/modules/roster/candidates.py`:

```python
import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.errors import BadRequest, NotFound
from app.core.time import utcnow
from app.modules.engagements.schemas import ProjectContext
from app.modules.engagements.service import staffed_project
from app.modules.governance.service import active_matching
from app.modules.roster.models import RosterProfile
from app.modules.roster.repository import RosterRepository
from app.modules.roster.schemas import Candidate, CandidateCard, CandidatePage, ScoreBreakdown
from app.modules.roster.scoring import ProjectNeeds, rank


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    skill_ids: tuple[UUID, ...] = ()
    availability: str | None = None
    location: str | None = None
    q: str | None = None


def project_needs(project: ProjectContext, today: date) -> ProjectNeeds:
    starts_on = max(project.starts_on or today, today)
    return ProjectNeeds(required_skill_ids=frozenset(project.required_skill_ids), starts_on=starts_on)


def card(profile: RosterProfile) -> CandidateCard:
    verified = set(profile.verified_skill_ids)
    return CandidateCard(
        worker_id=profile.worker_id,
        display_name=profile.display_name,
        standing_tier=profile.standing_tier,
        verified_skill_ids=sorted(verified, key=str),
        self_reported_skill_ids=sorted(set(profile.skill_ids) - verified, key=str),
        availability_status=profile.availability_status,
        available_from=profile.available_from,
        base_location=profile.base_location,
        engagements_total=profile.engagements_total,
    )


def _encode(breakdown: ScoreBreakdown, profile: RosterProfile) -> str:
    raw = json.dumps({"s": breakdown.total, "w": str(profile.worker_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode(cursor: str) -> tuple[float, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return float(data["s"]), str(UUID(data["w"]))
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise BadRequest("Invalid cursor", code="invalid_cursor") from exc


async def visible_project(session: AsyncSession, actor: Actor, project_id: UUID) -> ProjectContext:
    project = await staffed_project(session, actor.user_id, project_id)
    if project is None:
        raise NotFound("Project not found", code="project_not_found")
    return project


async def search(
    session: AsyncSession,
    actor: Actor,
    project_id: UUID,
    filters: CandidateFilters,
    cursor: str | None,
    limit: int,
) -> CandidatePage:
    project = await visible_project(session, actor, project_id)
    policy = await active_matching(session)
    profiles = await RosterRepository(session).eligible(
        project.data_region,
        skill_ids=filters.skill_ids,
        availability=filters.availability,
        location=filters.location,
        q=filters.q,
    )
    ranked = rank(profiles, project_needs(project, utcnow().date()), policy)
    if cursor is not None:
        after_total, after_worker = _decode(cursor)
        ranked = [
            (b, p)
            for b, p in ranked
            if (-b.total, str(p.worker_id)) > (-after_total, after_worker)
        ]
    page = ranked[:limit]
    return CandidatePage(
        items=[
            Candidate(worker=card(p), score=b.total, score_breakdown=b) for b, p in page
        ],
        next_cursor=_encode(*page[-1]) if len(ranked) > limit else None,
    )
```

`backend/app/modules/roster/router.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.identity.service import Permission, require_permission
from app.modules.passport.service import AvailabilityStatus
from app.modules.roster.candidates import CandidateFilters, search
from app.modules.roster.schemas import CandidatePage

router = APIRouter(prefix="/api/v1", tags=["roster"])

RosterSearcher = Annotated[Actor, Depends(require_permission(Permission.ROSTER_SEARCH))]


@router.get("/projects/{project_id}/candidates")
async def list_candidates(
    project_id: UUID,
    actor: RosterSearcher,
    session: SessionDep,
    skill_ids: Annotated[list[UUID] | None, Query(max_length=20)] = None,
    availability: AvailabilityStatus | None = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CandidatePage:
    filters = CandidateFilters(
        skill_ids=tuple(skill_ids or ()),
        availability=availability.value if availability else None,
        location=location,
        q=q,
    )
    return await search(session, actor, project_id, filters, cursor, limit)
```

In `backend/app/main.py`, import `from app.modules.roster.router import router as roster_router` and add `app.include_router(roster_router)` after the standing router.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/roster tests/api/test_visibility_guard.py -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(roster): scored candidate search with keyset cursor" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 4: First-shot panel with impression logging

**Files:**
- Create: `backend/alembic/versions/0011_first_shot.py`, `backend/app/modules/roster/first_shot.py`, `backend/app/modules/roster/enums.py`
- Modify: `backend/app/modules/roster/models.py`, `repository.py`, `schemas.py`, `router.py`
- Test: `backend/tests/unit/roster/test_first_shot.py`, `backend/tests/api/roster/test_first_shot_panel.py`

**Interfaces:**
- Consumes: `rank`, `availability_fit`, `ProjectNeeds` (Task 2); `visible_project`, `project_needs`, `card`, `RosterRepository.eligible` (Tasks 1, 3); `active_matching`.
- Produces:
  - Enums `FirstShotOutcome{SHOWN, SHORTLISTED, CONTACTED, ENGAGED, PASSED}` and `PassReason{SKILLS_MISMATCH, AVAILABILITY_MISMATCH, RATE_MISMATCH, LOCATION_MISMATCH, ALREADY_STAFFED, OTHER}` in `roster/enums.py`. The spec calls this list a fixed list of reason codes.
  - Model `FirstShotReview`, with:
    - unique constraint `uq_first_shot_reviews_project_worker`;
    - check `ck_first_shot_reviews_reason_matches_outcome`, meaning a reason is present exactly when the outcome is `passed`.
  - `FirstShotRepository(session)`:
    - `for_project(project_id) -> dict[UUID, FirstShotReview]`
    - `record_shown(project_id, worker_ids, pm_id)`, which inserts and does nothing on conflict
    - `get_for_update(project_id, worker_id)`
  - `first_shot.select_panel(profiles, *, project_id, needs, rules, exclude) -> list[RosterProfile]`, a pure function.
  - `first_shot.first_shot_panel(session, actor, project_id) -> FirstShotPanel`.
  - Schemas `FirstShotItem(worker: CandidateCard, outcome, reason_code)` and `FirstShotPanel(project_id, policy_version, items)`.
  - Route `GET /api/v1/projects/{project_id}/first-shot` (`FIRST_SHOT_REVIEW`).

Selection rules (spec §7.4). A worker is eligible for the first-shot panel when:
- they are base-eligible: status active or dormant, `profile_complete`, and region or consent eligible;
- they claim every required skill (self-reported or verified);
- their `availability_fit > 0`;
- their `engagements_last_12m ≤ underused_max_engagements_12m`;
- they are not among the top `exclude_top_candidates` of the unfiltered candidate ranking;
- they are not already `passed` or `engaged` for this project. This keeps the panel rotating to new people; it is a plan decision, recorded in Task 7.

Ranking:
1. Verified coverage of the required skills, descending.
2. `engagements_last_12m`, ascending.
3. `sha256(f"{project_id}:{worker_id}")`, which is deterministic per project and rotates across projects.

The panel takes the first `panel_size`, and it never filters by tier.

Serving the panel records a `shown` row for each worker in it that has no row yet. It never changes an existing outcome.

- [ ] **Step 1: Enums, model, migration**

`backend/app/modules/roster/enums.py`:

```python
import enum


class FirstShotOutcome(enum.StrEnum):
    SHOWN = "shown"
    SHORTLISTED = "shortlisted"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    PASSED = "passed"


class PassReason(enum.StrEnum):
    """Fixed reason codes for passing on a first-shot candidate (FR-4.7)."""

    SKILLS_MISMATCH = "skills_mismatch"
    AVAILABILITY_MISMATCH = "availability_mismatch"
    RATE_MISMATCH = "rate_mismatch"
    LOCATION_MISMATCH = "location_mismatch"
    ALREADY_STAFFED = "already_staffed"
    OTHER = "other"


DETAIL_OUTCOMES = frozenset(
    {FirstShotOutcome.SHORTLISTED, FirstShotOutcome.CONTACTED, FirstShotOutcome.ENGAGED}
)
DECIDED_OUTCOMES = frozenset({FirstShotOutcome.PASSED, FirstShotOutcome.ENGAGED})
```

Append to `backend/app/modules/roster/models.py`. Add these imports:
- `CheckConstraint` and `UniqueConstraint` from sqlalchemy;
- `TimestampMixin` and `UUIDPrimaryKeyMixin` from `app.core.db.base`;
- `pg_enum`;
- the two enums.

```python
class FirstShotReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Impression and outcome for one worker surfaced on one project's
    first-shot panel (FR-4.6, FR-4.7, NFR-5.2)."""

    __tablename__ = "first_shot_reviews"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    pm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    outcome: Mapped[FirstShotOutcome] = mapped_column(pg_enum(FirstShotOutcome), nullable=False)
    reason_code: Mapped[PassReason | None] = mapped_column(pg_enum(PassReason))

    __table_args__ = (
        UniqueConstraint("project_id", "worker_id", name="uq_first_shot_reviews_project_worker"),
        CheckConstraint(
            "(outcome = 'passed') = (reason_code IS NOT NULL)", name="reason_matches_outcome"
        ),
    )
```

`backend/alembic/versions/0011_first_shot.py`:

```python
"""roster: first_shot_reviews

Revision ID: 0011_first_shot
Revises: 0010_roster
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_first_shot"
down_revision: str | None = "0010_roster"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "first_shot_reviews",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("pm_id", _UUID, nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "shown", "shortlisted", "contacted", "engaged", "passed", name="firstshotoutcome"
            ),
            nullable=False,
        ),
        sa.Column(
            "reason_code",
            sa.Enum(
                "skills_mismatch",
                "availability_mismatch",
                "rate_mismatch",
                "location_mismatch",
                "already_staffed",
                "other",
                name="passreason",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_first_shot_reviews"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_first_shot_reviews_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_first_shot_reviews_worker_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pm_id"], ["user_accounts.id"], name="fk_first_shot_reviews_pm_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "project_id", "worker_id", name="uq_first_shot_reviews_project_worker"
        ),
        sa.CheckConstraint(
            "(outcome = 'passed') = (reason_code IS NOT NULL)",
            name=op.f("ck_first_shot_reviews_reason_matches_outcome"),
        ),
    )


def downgrade() -> None:
    op.drop_table("first_shot_reviews")
    op.execute("DROP TYPE passreason")
    op.execute("DROP TYPE firstshotoutcome")
```

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 2: Write the failing tests**

`backend/tests/unit/roster/test_first_shot.py`:

```python
from datetime import date
from uuid import UUID, uuid4

from app.modules.governance.schemas import MatchingRules
from app.modules.roster.first_shot import select_panel
from app.modules.roster.models import RosterProfile
from app.modules.roster.scoring import ProjectNeeds
from tests.support import _seed_policy_rows

RULES = MatchingRules.model_validate(
    next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
)
SKILL = uuid4()
NEEDS = ProjectNeeds(required_skill_ids=frozenset({SKILL}), starts_on=date(2026, 10, 1))


def _profile(
    *,
    claimed: bool = True,
    verified: bool = False,
    tier: str = "unrated",
    last_12m: int = 0,
    availability: str = "available",
) -> RosterProfile:
    return RosterProfile(
        worker_id=uuid4(),
        display_name="Test",
        status="dormant",
        onboarding_state="profile_complete",
        data_region="GH",
        cross_region_ok=False,
        standing_tier=tier,
        skill_ids=[SKILL] if claimed else [],
        verified_skill_ids=[SKILL] if verified else [],
        base_location=None,
        availability_status=availability,
        available_from=None,
        engagements_total=last_12m,
        engagements_last_12m=last_12m,
        last_engaged_on=None,
        refreshed_at=None,
    )


def _panel(
    profiles: list[RosterProfile],
    exclude: set[UUID] | None = None,
    project: UUID | None = None,
) -> list[RosterProfile]:
    return select_panel(
        profiles,
        project_id=project or UUID(int=1),
        needs=NEEDS,
        rules=RULES,
        exclude=exclude or set(),
    )


def test_only_qualified_available_underused_workers_are_eligible() -> None:
    ok = _profile()
    missing_skill = _profile(claimed=False)
    unavailable = _profile(availability="unavailable")
    busy = _profile(last_12m=2)

    assert _panel([ok, missing_skill, unavailable, busy]) == [ok]


def test_tier_never_filters_the_pool() -> None:
    unrated, trusted = _profile(tier="unrated"), _profile(tier="tier_2")

    assert set(p.worker_id for p in _panel([unrated, trusted])) == {
        unrated.worker_id,
        trusted.worker_id,
    }


def test_ranking_is_coverage_then_least_engaged() -> None:
    verified = _profile(verified=True, last_12m=1)
    fresh = _profile(last_12m=0)
    once = _profile(last_12m=1)

    assert _panel([once, fresh, verified]) == [verified, fresh, once]


def test_excluded_workers_and_panel_size() -> None:
    profiles = [_profile() for _ in range(8)]
    excluded = {profiles[0].worker_id}

    panel = _panel(profiles, exclude=excluded)

    assert len(panel) == RULES.first_shot.panel_size
    assert profiles[0] not in panel


def test_rotation_is_stable_per_project_and_differs_across_projects() -> None:
    profiles = [_profile() for _ in range(12)]

    first = [p.worker_id for p in _panel(profiles, project=UUID(int=1))]
    again = [p.worker_id for p in _panel(list(reversed(profiles)), project=UUID(int=1))]
    other = [p.worker_id for p in _panel(profiles, project=UUID(int=2))]

    assert first == again
    assert first != other
```

`backend/tests/api/roster/test_first_shot_panel.py`:

```python
import copy
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import Project
from app.modules.identity.models import UserAccount
from app.modules.roster.enums import FirstShotOutcome
from app.modules.roster.models import FirstShotReview
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)


async def _small_pool_policy(client: AsyncClient, session: AsyncSession, settings: Settings) -> None:
    """The seed excludes the top 10 candidates; tests use tiny pools."""
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 1
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/matching/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    activated = await client.post(
        f"/api/v1/policies/matching/versions/{proposed.json()['version']}/activate",
        headers=bearer(settings, approver),
    )
    assert activated.status_code == 200


async def _setup(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> tuple[UserAccount, Project]:
    await _small_pool_policy(client, session, settings)
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    for i in range(4):
        await make_ready_worker(session, email=f"w{i}@example.com", full_name=f"Worker {i}")
    await refresh_roster(session)
    return pm, project


async def test_the_panel_logs_shown_impressions_once(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project = await _setup(client, session, settings)
    url = f"/api/v1/projects/{project.id}/first-shot"

    first = await client.get(url, headers=bearer(settings, pm))
    second = await client.get(url, headers=bearer(settings, pm))

    body = first.json()
    assert first.status_code == 200
    assert len(body["items"]) == 3  # 4 eligible minus the top candidate
    assert {i["outcome"] for i in body["items"]} == {"shown"}
    assert body["policy_version"] == 2
    assert [i["worker"]["worker_id"] for i in second.json()["items"]] == [
        i["worker"]["worker_id"] for i in body["items"]
    ]
    rows = (await session.scalars(select(FirstShotReview))).all()
    assert len(rows) == 3
    assert {r.pm_id for r in rows} == {pm.id}


async def test_serving_again_never_downgrades_an_outcome(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project = await _setup(client, session, settings)
    url = f"/api/v1/projects/{project.id}/first-shot"
    shown = (await client.get(url, headers=bearer(settings, pm))).json()["items"][0]
    row = (
        await session.scalars(
            select(FirstShotReview).where(
                FirstShotReview.worker_id == shown["worker"]["worker_id"]
            )
        )
    ).one()
    row.outcome = FirstShotOutcome.SHORTLISTED
    await session.commit()

    again = (await client.get(url, headers=bearer(settings, pm))).json()["items"]

    outcomes = {i["worker"]["worker_id"]: i["outcome"] for i in again}
    assert outcomes[shown["worker"]["worker_id"]] == "shortlisted"


async def test_unstaffed_pm_cannot_open_the_panel(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, project = await _setup(client, session, settings)
    outsider = await make_user(session, role=UserRole.PM)

    response = await client.get(
        f"/api/v1/projects/{project.id}/first-shot", headers=bearer(settings, outsider)
    )

    assert (response.status_code, response.json()["code"]) == (404, "project_not_found")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/roster/test_first_shot.py tests/api/roster/test_first_shot_panel.py -v`
Expected: FAIL: `ImportError: cannot import name 'select_panel'`.

- [ ] **Step 4: Implement**

Append to `backend/app/modules/roster/repository.py`. Import `FirstShotReview`, `FirstShotOutcome`, and `pg_insert`, which is already imported:

```python
class FirstShotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def for_project(self, project_id: UUID) -> dict[UUID, FirstShotReview]:
        rows = await self.session.scalars(
            select(FirstShotReview).where(FirstShotReview.project_id == project_id)
        )
        return {r.worker_id: r for r in rows.all()}

    async def record_shown(
        self, project_id: UUID, worker_ids: Sequence[UUID], pm_id: UUID
    ) -> None:
        """Impression logging (FR-4.6). An existing outcome is never changed."""
        if not worker_ids:
            return
        await self.session.execute(
            pg_insert(FirstShotReview)
            .values(
                [
                    {
                        "project_id": project_id,
                        "worker_id": worker_id,
                        "pm_id": pm_id,
                        "outcome": FirstShotOutcome.SHOWN,
                    }
                    for worker_id in worker_ids
                ]
            )
            .on_conflict_do_nothing(constraint="uq_first_shot_reviews_project_worker")
        )

    async def get_for_update(self, project_id: UUID, worker_id: UUID) -> FirstShotReview | None:
        return await self.session.scalar(
            select(FirstShotReview)
            .where(FirstShotReview.project_id == project_id, FirstShotReview.worker_id == worker_id)
            .with_for_update()
        )
```

The bulk `pg_insert(...).values([...])` bypasses the ORM's Python-side defaults, so `id`, `created_at` and `updated_at` come from the server defaults. That is fine, because the table has `server_default` for all three.

Append to `backend/app/modules/roster/schemas.py`. Import `FirstShotOutcome` and `PassReason`:

```python
class FirstShotItem(BaseModel):
    worker: CandidateCard
    outcome: FirstShotOutcome
    reason_code: PassReason | None


class FirstShotPanel(BaseModel):
    """The mandatory first-shot resource (FR-4.6): shown on the same page as
    candidates, never hideable."""

    project_id: UUID
    policy_version: int
    items: list[FirstShotItem]
```

`backend/app/modules/roster/first_shot.py`:

```python
import hashlib
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.time import utcnow
from app.modules.governance.schemas import MatchingRules
from app.modules.governance.service import active_matching
from app.modules.roster.candidates import card, project_needs, visible_project
from app.modules.roster.enums import DECIDED_OUTCOMES
from app.modules.roster.models import RosterProfile
from app.modules.roster.repository import FirstShotRepository, RosterRepository
from app.modules.roster.schemas import FirstShotItem, FirstShotPanel
from app.modules.roster.scoring import ProjectNeeds, availability_fit, rank


def select_panel(
    profiles: Iterable[RosterProfile],
    *,
    project_id: UUID,
    needs: ProjectNeeds,
    rules: MatchingRules,
    exclude: set[UUID],
) -> list[RosterProfile]:
    """First-shot pool and ranking (spec §7.4). Never filtered by tier."""
    required = needs.required_skill_ids
    eligible = [
        p
        for p in profiles
        if p.worker_id not in exclude
        and required <= set(p.skill_ids)
        and availability_fit(
            p.availability_status, p.available_from, needs.starts_on, rules.availability_near_days
        )
        > 0
        and p.engagements_last_12m <= rules.first_shot.underused_max_engagements_12m
    ]

    def coverage(p: RosterProfile) -> float:
        return len(required & set(p.verified_skill_ids)) / len(required) if required else 0.0

    def rotation(p: RosterProfile) -> str:
        return hashlib.sha256(f"{project_id}:{p.worker_id}".encode()).hexdigest()

    eligible.sort(key=lambda p: (-coverage(p), p.engagements_last_12m, rotation(p)))
    return eligible[: rules.first_shot.panel_size]


async def first_shot_panel(session: AsyncSession, actor: Actor, project_id: UUID) -> FirstShotPanel:
    project = await visible_project(session, actor, project_id)
    policy = await active_matching(session)
    needs = project_needs(project, utcnow().date())
    profiles = await RosterRepository(session).eligible(project.data_region)
    reviews = FirstShotRepository(session)
    decided = {
        worker_id
        for worker_id, review in (await reviews.for_project(project.id)).items()
        if review.outcome in DECIDED_OUTCOMES
    }
    top = {
        p.worker_id
        for _, p in rank(profiles, needs, policy)[: policy.rules.first_shot.exclude_top_candidates]
    }
    panel = select_panel(
        profiles, project_id=project.id, needs=needs, rules=policy.rules, exclude=top | decided
    )
    await reviews.record_shown(project.id, [p.worker_id for p in panel], actor.user_id)
    current = await reviews.for_project(project.id)
    return FirstShotPanel(
        project_id=project.id,
        policy_version=policy.version,
        items=[
            FirstShotItem(
                worker=card(p),
                outcome=current[p.worker_id].outcome,
                reason_code=current[p.worker_id].reason_code,
            )
            for p in panel
        ],
    )
```

After the bulk insert, `for_project` re-reads the rows. The session may already hold rows loaded by the first `for_project` call and serve them from the identity map. That is fine: those rows did not change, and the new rows are loaded fresh.

Add to `backend/app/modules/roster/router.py`. Import `first_shot_panel` and `FirstShotPanel`:

```python
FirstShotReviewer = Annotated[Actor, Depends(require_permission(Permission.FIRST_SHOT_REVIEW))]


@router.get("/projects/{project_id}/first-shot")
async def get_first_shot(
    project_id: UUID, actor: FirstShotReviewer, session: SessionDep
) -> FirstShotPanel:
    return await first_shot_panel(session, actor, project_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/roster tests/api/roster tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 6: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(roster): first-shot panel with impression logging" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 5: First-shot reviews and the first-shot visibility source

**Files:**
- Create: `backend/app/modules/roster/visibility.py`
- Modify: `backend/app/modules/roster/first_shot.py`, `schemas.py`, `router.py`, `service.py`, `backend/app/wiring.py`
- Test: `backend/tests/api/roster/test_first_shot_reviews.py`

**Interfaces:**
- Consumes:
  - `FirstShotRepository.get_for_update` (Task 4)
  - `visible_project` (Task 3)
  - `staffed_project_ids` (Task 3)
  - `require_visibility` and `Visibility` (identity.service)
- Produces:
  - Schemas:
    - `FirstShotReviewCreate(outcome: Literal[shortlisted, contacted, engaged, passed], reason_code: PassReason | None)`. It enforces that `passed` has a reason and every other outcome has none; a violation returns 422.
    - `FirstShotReviewRead(project_id, worker_id, outcome, reason_code, pm_id, updated_at)`.
  - `first_shot.review(session, actor, project_id, worker_id, data) -> FirstShotReview`.
  - Route `POST /api/v1/projects/{project_id}/first-shot/{worker_id}/review`. It requires `FIRST_SHOT_REVIEW` and passes the visibility guard at `SUMMARY`.
  - Error code `not_in_first_shot` (404).
  - Visibility source `first_shot_relationship(session, actor, worker_id) -> Visibility`. It is exported from `roster.service` and registered in `app.wiring.visibility_sources()`.

The spec (§7.1, §7.4) says `shortlisted`, `contacted` and `engaged` give the PM detail visibility for that worker, and `passed` does not. This holds only while the PM staffs the project: staffing is read live, as in 2B. A review is possible only for a worker already shown on that project's panel. Every review is audited as `first_shot.reviewed`, with no free text.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/roster/test_first_shot_reviews.py`:

```python
import copy
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.models import Project, ProjectStaff
from app.modules.identity.models import UserAccount
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)


async def _panel(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> tuple[UserAccount, Project, str]:
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 0
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/matching/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    await client.post(
        f"/api/v1/policies/matching/versions/{proposed.json()['version']}/activate",
        headers=bearer(settings, approver),
    )
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="EU")
    worker, account = await make_ready_worker(session, data_region="GH")
    await client.put(
        "/api/v1/workers/me/consents/cross_region_matching",
        json={"granted": True},
        headers=bearer(settings, account),
    )
    await refresh_roster(session)
    items = (
        await client.get(f"/api/v1/projects/{project.id}/first-shot", headers=bearer(settings, pm))
    ).json()["items"]
    assert [i["worker"]["worker_id"] for i in items] == [str(worker.id)]
    return pm, project, str(worker.id)


def _review_url(project: Project, worker_id: str) -> str:
    return f"/api/v1/projects/{project.id}/first-shot/{worker_id}/review"


async def _view(client: AsyncClient, settings: Settings, pm: UserAccount, worker_id: str) -> str | None:
    response = await client.get(f"/api/v1/workers/{worker_id}", headers=bearer(settings, pm))
    return response.json()["view"] if response.status_code == 200 else None


async def test_shortlisting_grants_detail_and_is_audited(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    before = await _view(client, settings, pm, worker_id)

    response = await client.post(
        _review_url(project, worker_id),
        json={"outcome": "shortlisted"},
        headers=bearer(settings, pm),
    )

    assert response.status_code == 200
    assert (response.json()["outcome"], response.json()["reason_code"]) == ("shortlisted", None)
    assert (before, await _view(client, settings, pm, worker_id)) == ("summary", "detail")
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "first_shot.reviewed"))
    ).one()
    assert (audit.actor_id, str(audit.target_id)) == (pm.id, worker_id)
    assert audit.after == {
        "project_id": str(project.id),
        "outcome": "shortlisted",
        "reason_code": None,
    }


async def test_passing_needs_a_reason_and_never_grants_detail(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    url = _review_url(project, worker_id)
    headers = bearer(settings, pm)

    no_reason = await client.post(url, json={"outcome": "passed"}, headers=headers)
    stray_reason = await client.post(
        url, json={"outcome": "contacted", "reason_code": "other"}, headers=headers
    )
    passed = await client.post(
        url, json={"outcome": "passed", "reason_code": "rate_mismatch"}, headers=headers
    )

    assert (no_reason.status_code, stray_reason.status_code, passed.status_code) == (422, 422, 200)
    assert await _view(client, settings, pm, worker_id) == "summary"


async def test_detail_ends_when_staffing_ends(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    await client.post(
        _review_url(project, worker_id), json={"outcome": "engaged"}, headers=bearer(settings, pm)
    )
    await session.execute(update(ProjectStaff).values(active_to=utcnow()))
    await session.commit()

    assert await _view(client, settings, pm, worker_id) is None


@pytest.mark.parametrize("who", ["not_shown", "outsider"])
async def test_reviews_need_a_shown_worker_and_a_staffed_pm(
    client: AsyncClient, session: AsyncSession, settings: Settings, who: str
) -> None:
    pm, project, worker_id = await _panel(client, session, settings)
    if who == "not_shown":
        other, _ = await make_ready_worker(session, email="other@example.com", data_region="EU")
        response = await client.post(
            _review_url(project, str(other.id)),
            json={"outcome": "shortlisted"},
            headers=bearer(settings, pm),
        )
        expected = (404, "not_in_first_shot")
    else:
        outsider = await make_user(session, role=UserRole.PM)
        await make_project(session, staff=[outsider], data_region="EU", name="Theirs")
        response = await client.post(
            _review_url(project, worker_id),
            json={"outcome": "shortlisted"},
            headers=bearer(settings, outsider),
        )
        expected = (404, "project_not_found")

    assert (response.status_code, response.json()["code"]) == expected
```

In the `outsider` case, the outsider staffs an EU project while the worker has cross-region consent. That gives the outsider summary visibility, so the guard passes and the project check answers. In the `not_shown` case, the other worker is in the project's region (EU), so the PM has summary visibility. Consequently `not_in_first_shot` comes from the service, not the guard.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/roster/test_first_shot_reviews.py -v`
Expected: FAIL, with 404/405 on the review route.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/roster/schemas.py`. Import `Literal`, `Self`, `datetime`, `ConfigDict` and `model_validator`:

```python
class FirstShotReviewCreate(BaseModel):
    """FR-4.7: an outcome, and a fixed reason code when passing."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["shortlisted", "contacted", "engaged", "passed"]
    reason_code: PassReason | None = None

    @model_validator(mode="after")
    def _reason_only_when_passing(self) -> Self:
        if (self.outcome == "passed") != (self.reason_code is not None):
            raise ValueError("reason_code is required when passing and only then")
        return self


class FirstShotReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    worker_id: UUID
    outcome: FirstShotOutcome
    reason_code: PassReason | None
    pm_id: UUID | None
    updated_at: datetime
```

Append to `backend/app/modules/roster/first_shot.py`. Add these imports:
- `write_audit`
- `NotFound`
- `FirstShotOutcome` and `PassReason`
- `FirstShotReviewCreate`
- `FirstShotReview`

```python
async def review(
    session: AsyncSession,
    actor: Actor,
    project_id: UUID,
    worker_id: UUID,
    data: FirstShotReviewCreate,
) -> FirstShotReview:
    project = await visible_project(session, actor, project_id)
    row = await FirstShotRepository(session).get_for_update(project.id, worker_id)
    if row is None:
        raise NotFound(
            "This worker has not been shown on this project's first-shot panel",
            code="not_in_first_shot",
        )
    row.outcome = FirstShotOutcome(data.outcome)
    row.reason_code = data.reason_code
    row.pm_id = actor.user_id
    await session.flush()
    await write_audit(
        session,
        actor=actor,
        action="first_shot.reviewed",
        target_type="worker",
        target_id=worker_id,
        after={
            "project_id": str(project.id),
            "outcome": row.outcome.value,
            "reason_code": row.reason_code.value if row.reason_code else None,
        },
    )
    return row
```

Append to `FirstShotRepository` in `backend/app/modules/roster/repository.py` (imports: `exists`, `DETAIL_OUTCOMES`):

```python
    async def has_detail_outcome(self, worker_id: UUID, project_ids: Sequence[UUID]) -> bool:
        if not project_ids:
            return False
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        FirstShotReview.worker_id == worker_id,
                        FirstShotReview.project_id.in_(project_ids),
                        FirstShotReview.outcome.in_(DETAIL_OUTCOMES),
                    )
                )
            )
        )
```

`backend/app/modules/roster/visibility.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.enums import UserRole
from app.modules.engagements.service import staffed_project_ids
from app.modules.identity.service import Visibility
from app.modules.roster.repository import FirstShotRepository


async def first_shot_relationship(
    session: AsyncSession, actor: Actor, worker_id: UUID
) -> Visibility:
    """Spec §7.1: shortlisting, contacting or engaging a first-shot worker on a
    project the PM staffs gives detail; passing does not. Staffing is read live."""
    if actor.role is not UserRole.PM:
        return Visibility.NONE
    projects = await staffed_project_ids(session, actor.user_id)
    if await FirstShotRepository(session).has_detail_outcome(worker_id, projects):
        return Visibility.DETAIL
    return Visibility.NONE
```

Replace `backend/app/modules/roster/service.py`:

```python
"""Public interface of the roster module. No other module imports it; the
composition root wires its handlers, router and visibility source."""

from app.modules.roster.refresh import rebuild_all
from app.modules.roster.visibility import first_shot_relationship

__all__ = ["first_shot_relationship", "rebuild_all"]
```

In `backend/app/wiring.py`, import `first_shot_relationship` from `app.modules.roster.service` and return it from `visibility_sources()`, as in `[project_relationship, first_shot_relationship]`.

Add the following to `backend/app/modules/roster/router.py`. Import `Visibility`, `require_visibility`, `review`, `FirstShotReviewCreate` and `FirstShotReviewRead`:

```python
@router.post("/projects/{project_id}/first-shot/{worker_id}/review")
async def review_first_shot(
    project_id: UUID,
    worker_id: UUID,
    body: FirstShotReviewCreate,
    actor: FirstShotReviewer,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> FirstShotReviewRead:
    return FirstShotReviewRead.model_validate(
        await review(session, actor, project_id, worker_id, body)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/roster tests/api/test_visibility_guard.py tests/api/engagements/test_visibility_sources.py -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(roster): first-shot review outcomes and first-shot visibility source" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 6: Carry-forward: the standing explanation reports the evaluated tier

**Files:**
- Modify: `backend/app/modules/standing/schemas.py`, `backend/app/modules/standing/explanation.py`
- Test: `backend/tests/api/standing/test_explanation.py`

**Interfaces:**
- Consumes: `standing_explanation` (Plan 3A).
- Produces: `StandingExplanation.evaluated_tier: StandingTier`. It is the tier the active policy gives today, alongside the stored `tier`.

This closes the 3B roadmap row. The explanation shows the stored tier next to live factors and the active policy version. Those can disagree until the handler or the nightly run catches up. With `evaluated_tier`, the page can say "your tier will update to …" instead of showing factors that do not match the tier.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/standing/test_explanation.py`:

```python
async def test_the_evaluated_tier_shows_a_pending_change(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, account = await make_ready_worker(session)
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=(await make_project(session)).id
    )
    await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)

    body = (
        await client.get("/api/v1/workers/me/standing", headers=bearer(settings, account))
    ).json()

    assert (body["tier"], body["evaluated_tier"]) == ("unrated", "tier_1")
```

Also add `assert body["evaluated_tier"] == "tier_1"` to `test_worker_sees_tier_factors_thresholds_and_history`, where the stored and evaluated tiers agree.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/standing/test_explanation.py -v`
Expected: FAIL with `KeyError: 'evaluated_tier'`.

- [ ] **Step 3: Implement**

In `backend/app/modules/standing/schemas.py`, add `evaluated_tier: StandingTier` to `StandingExplanation`, right after `tier`, with a docstring line:

```python
    tier: StandingTier
    # The tier the active policy gives today; differs from `tier` until the
    # recalculation handler or the nightly run records the change.
    evaluated_tier: StandingTier
```

In `backend/app/modules/standing/explanation.py`, pass `evaluated_tier=StandingTier(evaluation.tier)` when building `StandingExplanation`. Import `StandingTier` from `app.modules.passport.service`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/standing -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(standing): report the evaluated tier alongside the stored one" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 7: End-to-end staffing journey, roadmap and docs

**Files:**
- Create: `backend/tests/api/test_staffing_journey.py`
- Modify: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`, `PROJECT_STRUCTURE.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the end-to-end test**

`backend/tests/api/test_staffing_journey.py`:

```python
"""The MVA's fairness loop (spec §10): a PM staffing a project sees scored
candidates and, on the same page, a first-shot panel of qualified underused
workers; shortlisting one opens their detail; the roster follows events."""

import copy
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


async def test_candidates_first_shot_and_shortlisting(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    # People Ops set a matching policy suited to a small pool.
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 1
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/matching/versions", json={"rules": rules}, headers=bearer(settings, author)
    )
    assert (
        await client.post(
            f"/api/v1/policies/matching/versions/{proposed.json()['version']}/activate",
            headers=bearer(settings, approver),
        )
    ).status_code == 200

    # Three qualified workers: Ama is verified and busy, Kofi and Esi are underused.
    pm = await make_user(session, role=UserRole.PM)
    ama, _ = await make_ready_worker(session, email="ama@example.com", full_name="Ama")
    kofi, _ = await make_ready_worker(session, email="kofi@example.com", full_name="Kofi")
    esi, esi_account = await make_ready_worker(session, email="esi@example.com", full_name="Esi")
    skill = (await session.scalars(select(Skill))).one()
    ama_claim = (
        await session.scalars(select(SkillClaim).where(SkillClaim.worker_id == ama.id))
    ).one()
    ama_claim.verification_status = VerificationStatus.BONARDA_VERIFIED
    await session.commit()
    past = await make_project(session, name="Past")
    for days in (30, 60):
        await make_engagement(
            session,
            worker_id=ama.id,
            project_id=past.id,
            start_date=utcnow().date() - timedelta(days=days),
        )
    project = await make_project(
        session,
        staff=[pm],
        name="Tema",
        required_skill_ids=[skill.id],
        starts_on=utcnow().date() + timedelta(days=7),
    )
    await refresh_roster(session)
    headers = bearer(settings, pm)

    # 1. Candidates: Ama ranks first on verified coverage.
    candidates = (
        await client.get(f"/api/v1/projects/{project.id}/candidates", headers=headers)
    ).json()["items"]
    assert candidates[0]["worker"]["display_name"] == "Ama"
    assert candidates[0]["score_breakdown"]["policy_version"] == 2

    # 2. First-shot: Ama is excluded (top candidate and busy); Kofi and Esi are shown.
    panel = (await client.get(f"/api/v1/projects/{project.id}/first-shot", headers=headers)).json()
    shown = {i["worker"]["display_name"]: i["worker"]["worker_id"] for i in panel["items"]}
    assert set(shown) == {"Kofi", "Esi"}

    # 3. Shortlisting Esi opens her detail view.
    reviewed = await client.post(
        f"/api/v1/projects/{project.id}/first-shot/{shown['Esi']}/review",
        json={"outcome": "shortlisted"},
        headers=headers,
    )
    assert reviewed.status_code == 200
    detail = await client.get(f"/api/v1/workers/{shown['Esi']}", headers=headers)
    assert detail.json()["view"] == "detail"

    # 4. Esi becomes unavailable; the roster follows and she leaves the candidates.
    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "unavailable"},
        headers=bearer(settings, esi_account),
    )
    await drain()
    after = (await client.get(f"/api/v1/projects/{project.id}/candidates", headers=headers)).json()
    scores = {c["worker"]["worker_id"]: c["score_breakdown"] for c in after["items"]}
    assert scores[str(esi.id)]["availability"]["points"] == 0.0
    assert scores[str(kofi.id)]["availability"]["points"] == 0.15
```

Run: `pytest tests/api/test_staffing_journey.py -v`
Expected: PASS. If it fails, the failure points to an integration gap. Fix it in the owning module if the fix is small and obvious, and name it in your report.

- [ ] **Step 2: Update the roadmap**

Make these changes in `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`.

**Plan table**

Set the 3B row's file to `2026-09-26-bonarda-03b-roster.md` and its status to `Written`.

**Carry-forward**

Delete the `3B` row about the standing explanation's stored and live values; Task 6 closes it.

Add these rows:
- `any`: candidate scoring and first-shot selection score the whole eligible pool in Python per request. That is fine at the pilot's 5,000 profiles. Push scoring into SQL, or cache ranked pools per project, if the pool grows well beyond that.
- `5`: the SPA renders the first-shot panel in the same page layout as candidates, and no toggle can hide it (spec §7.8 `useFirstShot`).
- `4`: a first-shot `engaged` outcome is recorded by the PM; it is not derived from an actual engagement on the project. Consider setting it automatically when the PM engages that worker on the project.
- `4`: concentration rollups (`first_shot_shown`, `first_shot_engaged`) read `first_shot_reviews`.
- `any`: the lock-order row gains roster refreshes. They are serialized per worker with a transaction-level advisory lock (`pg_advisory_xact_lock`), taken before any other lock in the refresh.

**Deviations (Plan 3B rows)**

| Plan | Change | Reason |
|---|---|---|
| 3B | `roster_profiles.last_engaged_on` is a date (the latest engagement start), not `last_engaged_at` | Engagements carry start dates, not start times |
| 3B | Roster status, tier and availability columns are plain strings | The roster is a projection and does not share passport's DB enum types |
| 3B | "Last 12 months" means the last 365 days of engagement start dates | Simple, and stable across month lengths |
| 3B | Candidates are paginated with an opaque cursor over the computed score order | Scores are computed per request; the cursor keeps keyset semantics over them |
| 3B | The first-shot panel leaves out workers already `passed` or `engaged` for the project | The panel keeps surfacing new people instead of re-showing decided ones |
| 3B | Candidates and the first-shot panel include only `profile_complete` workers | An invited worker cannot yet be engaged (FR-5.1) |

Add one row only if Task 1 had to drop the trigram index:

| Plan | Change | Reason |
|---|---|---|
| 3B | The trigram name index was dropped | Alembic model-migration parity; `ILIKE` is enough for 5,000 rows |

- [ ] **Step 3: Update PROJECT_STRUCTURE.md**

Under `modules/`, replace any roster placeholder line with the block below. If there is none, add the block after `standing/`:

```
│   │   │   ├── roster/                    # read-model, scoring, candidates, first-shot (Plan 3B)
│   │   │   │   ├── enums.py, models.py, repository.py, schemas.py
│   │   │   │   ├── refresh.py, scoring.py, candidates.py, first_shot.py, visibility.py
│   │   │   │   ├── handlers.py, router.py
│   │   │   │   └── service.py
```

- [ ] **Step 4: Full verification**

Run from `backend/`: `ruff format --check . && ruff check . && mypy && lint-imports && pytest --cov=app --cov-report=term-missing`
Expected: all pass. Put the test count and the TOTAL coverage in the commit body.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend docs PROJECT_STRUCTURE.md
git commit -m "test: end-to-end staffing journey; record Plan 3B in roadmap and docs" -m "<test count and coverage>" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

## Spec coverage for this plan

| Spec / carry-forward item | Task |
|---|---|
| §5.2 rule 4: the roster never joins other modules' tables; it maintains `roster_profiles` from events and a nightly rebuild | 1 |
| §6.1 `roster_profiles`; §6.4 roster indexes (GIN skills, region/availability, trigram name, engagements_last_12m) | 1 |
| §7.7 `roster.refresh_worker` on worker, standing, consent and engagement events; nightly `roster_rebuild` | 1 |
| §8.5 withdrawing consent removes a cross-region worker within one relay cycle | 1, 3 |
| §7.4 candidate score with `score_breakdown`; FR-3.4 tier capped at 15%; FR-6.2 no selection-frequency or engagement-count weight | 2 |
| §7.2 `GET /projects/{id}/candidates` (summary level, keyset pagination, filters); §2.2 #2 search needs a project context | 3 |
| §7.4 first-shot pool, underused threshold, top-N exclusion, ranking, rotation, panel size; FR-4.6 mandatory resource | 4 |
| §7.4 impression logging (`shown`); `first_shot_reviews` unique per project and worker | 4 |
| §7.2 `POST …/first-shot/{worker_id}/review`; FR-4.7 outcome and reason code; §7.1 detail through shortlisted, contacted or engaged | 5 |
| Carry-forward: standing explanation stored vs live tier | 6 |

These items are deferred, and Task 7 records them:
- SPA rendering of the first-shot panel (Plan 5)
- deriving `engaged` from real engagements (Plan 4)
- concentration rollups over first-shot data (Plan 4)
- SQL scoring at scale (any plan)

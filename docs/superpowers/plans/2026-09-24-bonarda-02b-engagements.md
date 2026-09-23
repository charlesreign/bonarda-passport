# Bonarda Plan 2B — Engagements and Reactivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `engagements` module — projects and staffing, PM visibility sources, first-time engagements, reactivation with prefill and idempotency, contract dispatch through an e-signature adapter, a signed e-sign webhook, activation and payroll signalling, completion, structured feedback and a stuck-contract detector — plus the Plan 2A carry-forward items the roadmap assigns to 2B.

**Architecture:** Builds on Plans 1 and 2A (branch `feat/worker-passport`). `engagements` is a new module at `app/modules/engagements/` with its own router, services, repository, models, schemas, handlers and visibility source, exposed through `service.py`. Engagement routes address the worker in the path (`/workers/{worker_id}/engagements`, `/workers/{worker_id}/reactivations`) so the visibility guard covers them; managed actions on an existing engagement use `/engagements/{engagement_id}/…` and require the PM to be staffed on its project. Every external call (e-sign, payroll) happens only inside outbox handlers in the worker, with adapters injected through `HandlerDeps`. Dependencies flow one way: `engagements` → `passport.service` / `identity.service` / `integrations.service`; passport never imports engagements.

**Tech Stack:** Python 3.12, FastAPI 0.115 (pinned), Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis, Arq, pytest + Testcontainers + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md` (§5 modules, §6.1/6.4 data, §7.1 visibility, §7.2 engagement API, §7.5 reactivation sequence, §7.7 background work, §8.4 reliability). Roadmap with carry-forward and deviations: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`.

## Global Constraints

- Work on branch `feat/worker-passport` (Plans 1 + 2A). All commands run from `backend/` with the venv at `backend/.venv` activated (`source .venv/Scripts/activate` in Git Bash). Docker must be running (Testcontainers Postgres).
- All routes are under `/api/v1`. Errors are RFC 9457 `application/problem+json` with a stable `code` field.
- A module imports another module only through its `service` or `schemas` submodule. `app/main.py`, `app/worker/` and `app/wiring.py` are the composition root and may import anything. `app.core` imports no module. `passport` never imports `engagements`.
- Every state change of administrative, security, contractual or privacy significance writes `write_audit(...)` on the request's (or handler's) `AsyncSession`; every change other modules must react to emits `emit_event(...)` on the same session. Audit rows about workers carry no contact data and no free-text feedback.
- Request code never calls an external system and never enqueues Arq jobs: e-sign and payroll calls happen only in outbox handlers, through the adapters in `HandlerDeps`.
- Workers are addressed in URL paths. Request bodies never carry a `worker_id` field (enforced by `tests/api/test_visibility_guard.py`).
- Integrity errors are mapped by constraint name via `app.core.db.errors.violated_constraint(exc)`; any other integrity error is re-raised, never relabelled.
- Enum columns use `app.core.db.types.pg_enum`. In migrations, check-constraint names go through `op.f("ck_<table>_<name>")`; unique, foreign-key, primary-key and index names are plain strings.
- Datetimes are timezone-aware UTC (`app.core.time.utcnow()`); "today" is `utcnow().date()`. Money is `decimal.Decimal` stored as `Numeric(12, 2)`; currency is an ISO 4217 code.
- Async tests never call `session.expire_all()` followed by `session.get(...)`; use `await session.refresh(obj)`.
- Before every commit: `ruff format . && ruff check . && mypy && lint-imports && pytest` — all must pass.
- Commit messages end with a `Co-Authored-By:` trailer naming the model that wrote the commit.

## Review Focus

1. **A PM double-clicks "Reactivate"** (the same `Idempotency-Key` sent twice): exactly one engagement exists and the second request returns it with 200. (Test in Task 4.)
2. **The e-sign provider delivers the same webhook twice, or a `signed` event for an engagement that was already cancelled or activated**: no second activation, no second payroll signal, no second audit row. (Test in Task 6.)
3. **A PM removed from a project** (staff change or SCIM deactivation) loses the visibility and the actions that staffing gave them, immediately. (Tests in Tasks 1 and 2.)
4. **A contract signed before its start date** is not billable until that date; the hourly job activates it exactly once. (Test in Task 6.)
5. **A worker who removes their location, languages or last skill after onboarding** cannot be given a first-time engagement until they fix it. (Test in Task 3.)

---

## File Structure

```
backend/
  alembic/versions/0006_projects.py            projects, project_staff (Task 1)
  alembic/versions/0007_engagements.py         engagements, feedback (Task 2)
  app/
    core/config.py                             + data_regions, esign/payroll settings, stuck thresholds
    core/errors.py                             + UnprocessableEntity (Task 9)
    core/db/errors.py                          violated_constraint() (Task 3)
    wiring.py                                  HandlerDeps + esign/payroll; engagements handlers; visibility source
    models_registry.py                         + engagements models
    main.py                                    + engagements router
    worker/jobs.py, worker/settings.py         activate_due_engagements, flag_stuck_engagements crons; adapters
    modules/engagements/
      __init__.py
      enums.py                                 ProjectStatus, EngagementPath, EngagementStatus, WorkMode
      models.py                                Project, ProjectStaff, Engagement, Feedback
      repository.py                            ProjectRepository, EngagementRepository
      schemas.py                               request/response models, events
      projects.py                              ProjectService, end_staffing_for()
      visibility.py                            project_relationship() visibility source
      engagements.py                           EngagementService (create, prefill, complete, managed())
      contracts.py                             send_contract(), ContractService (webhook, retry), activate(), activate_due()
      payroll.py                               signal_payroll()
      feedback.py                              FeedbackService
      stuck.py                                 flag_stuck()
      handlers.py                              register(registry, *, esign, payroll)
      router.py
      service.py                               public facade
    modules/integrations/
      esign.py                                 ContractDocument, EsignAdapter, FakeEsignAdapter
      payroll.py                               PayrollActivation, PayrollAdapter, FakePayrollAdapter
      webhooks.py                              sign_payload(), verify_signature()
      service.py                               + build_esign, build_payroll, exports
    modules/passport/
      queries.py                               existing_skill_ids, worker_region, profile_gaps, engagement_readiness,
                                               worker_name, claimed_skill_ids, mark_worker_active/dormant
      service.py, schemas.py, profile.py, skills.py, invitations.py, router.py   (carry-forward edits)
    modules/identity/
      accounts.py, service.py, grants.py, scim.py, schemas.py                   (new queries; carry-forward edits)
  pyproject.toml                               coverage greenlet concurrency (Task 10)
  tests/support.py, tests/conftest.py          make_ready_worker, make_project, make_engagement, engagement_terms,
                                               esign_webhook; esign/payroll fixtures
  tests/api/engagements/…                      one file per task
docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md, PROJECT_STRUCTURE.md   (Task 11)
```

---

### Task 1: Projects, staffing and data-region validation

**Files:**
- Create: `backend/app/modules/engagements/__init__.py`, `enums.py`, `models.py`, `repository.py`, `schemas.py`, `projects.py`, `handlers.py`, `router.py`, `service.py`; `backend/app/modules/passport/queries.py`; `backend/alembic/versions/0006_projects.py`
- Modify: `backend/app/core/config.py`, `backend/app/modules/identity/accounts.py`, `backend/app/modules/identity/service.py`, `backend/app/modules/passport/service.py`, `backend/app/modules/passport/invitations.py`, `backend/app/modules/passport/router.py`, `backend/app/models_registry.py`, `backend/app/wiring.py`, `backend/app/main.py`, `backend/tests/support.py`
- Test: `backend/tests/api/engagements/__init__.py`, `backend/tests/api/engagements/test_projects.py`, `backend/tests/api/engagements/test_staffing.py`, `backend/tests/api/passport/test_invitations.py`

**Interfaces:**
- Consumes: `write_audit`, `emit_event`, `CurrentActor`, `require_permission`, `Permission`, `SettingsDep`; identity `AccessRevoked` event (identity.schemas).
- Produces:
  - `Settings.data_regions: list[str]` (default `["GH", "EU"]`).
  - Enums (all Task-1, used later): `ProjectStatus{ACTIVE, CLOSED}`, `EngagementPath{FIRST_TIME, REACTIVATION}`, `EngagementStatus{PENDING_SIGNATURE, AWAITING_SIGNATURE, SIGNED, ACTIVE, COMPLETED, CANCELLED}`, `WorkMode{REMOTE, ONSITE, HYBRID}`, `OPEN_STATUSES`.
  - Models `Project`, `ProjectStaff`; `ProjectRepository(session)` with `get`, `add`, `add_staff`, `list_all`, `list_staffed_by(user_id)`, `is_staffed(project_id, user_id)`, `active_staff_ids(project_id)`, `active_staff_rows(project_id)`, `active_rows_for_user(user_id)`.
  - Schemas `ProjectCreate`, `ProjectRead`, `StaffAssignment`.
  - `ProjectService(session, settings)`: `create`, `read`, `list_visible`, `set_staff`, `visible(actor, project_id) -> Project`; `end_staffing_for(session, user_id, *, reason)`.
  - Identity: `active_pm_ids(session, user_ids) -> set[UUID]`; `identity.service` also exports `has_permission`.
  - Passport: `queries.existing_skill_ids(session, ids) -> set[UUID]`, exported from `passport.service`.
  - Routes `POST /api/v1/projects` (201), `GET /api/v1/projects`, `GET /api/v1/projects/{project_id}`, `PUT /api/v1/projects/{project_id}/staff`.
  - Handler `engagements.end_staffing_on_revocation` on `identity.access_revoked`.
  - Error codes: `unknown_data_region` (400), `unknown_skill` (400), `project_not_found` (404), `staff_not_active_pm` (400).
  - Test helper `make_project(session, *, staff=None, data_region="GH", name="Project Volta", required_skill_ids=None) -> Project`.

Visibility of projects: people_ops and admin see all projects; a PM sees the projects they are actively staffed on; everyone else is refused (`GET /projects` → 403, `GET /projects/{id}` → 404). A PM who creates a project is staffed on it automatically.

- [ ] **Step 1: Settings, enums, models, migration**

In `backend/app/core/config.py`, add to `Settings` after `mail_from`:

```python
    # Regions a worker or project can belong to (NFR-4.3). Pilot: Ghana + one EU country.
    data_regions: list[str] = Field(default_factory=lambda: ["GH", "EU"])
```

`backend/app/modules/engagements/__init__.py`: empty file.

`backend/app/modules/engagements/enums.py`:

```python
import enum


class ProjectStatus(enum.StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class EngagementPath(enum.StrEnum):
    FIRST_TIME = "first_time"  # FR-5.1
    REACTIVATION = "reactivation"  # FR-4.3


class EngagementStatus(enum.StrEnum):
    PENDING_SIGNATURE = "pending_signature"  # recorded; contract not yet sent
    AWAITING_SIGNATURE = "awaiting_signature"  # envelope sent
    SIGNED = "signed"  # signed; start date still ahead
    ACTIVE = "active"  # billable
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkMode(enum.StrEnum):
    REMOTE = "remote"
    ONSITE = "onsite"
    HYBRID = "hybrid"


OPEN_STATUSES = frozenset(
    {
        EngagementStatus.PENDING_SIGNATURE,
        EngagementStatus.AWAITING_SIGNATURE,
        EngagementStatus.SIGNED,
        EngagementStatus.ACTIVE,
    }
)
```

`backend/app/modules/engagements/models.py`:

```python
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.engagements.enums import ProjectStatus


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(200))
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    required_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("'{}'"), nullable=False
    )
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus),
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE.value,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on", name="dates_ordered"
        ),
    )


class ProjectStaff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The data behind PM scoping (FR-9.4). Ended rows keep history."""

    __tablename__ = "project_staff"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    user_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_project_staff_active_user",
            "user_account_id",
            postgresql_where=text("active_to IS NULL"),
        ),
        Index(
            "uq_project_staff_active",
            "project_id",
            "user_account_id",
            unique=True,
            postgresql_where=text("active_to IS NULL"),
        ),
    )
```

`backend/alembic/versions/0006_projects.py`:

```python
"""engagements: projects and project_staff

Revision ID: 0006_projects
Revises: 0005_passport
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_projects"
down_revision: str | None = "0005_passport"
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
        "projects",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("client_name", sa.String(200), nullable=True),
        sa.Column("data_region", sa.String(8), nullable=False),
        sa.Column(
            "required_skill_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "closed", name="projectstatus"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["user_accounts.id"], name="fk_projects_created_by_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name=op.f("ck_projects_dates_ordered"),
        ),
    )

    op.create_table(
        "project_staff",
        _id(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_project_staff"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_project_staff_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"], ["user_accounts.id"], name="fk_project_staff_user_account_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_project_staff_active_user",
        "project_staff",
        ["user_account_id"],
        postgresql_where=sa.text("active_to IS NULL"),
    )
    op.create_index(
        "uq_project_staff_active",
        "project_staff",
        ["project_id", "user_account_id"],
        unique=True,
        postgresql_where=sa.text("active_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_staff_active", table_name="project_staff")
    op.drop_index("ix_project_staff_active_user", table_name="project_staff")
    op.drop_table("project_staff")
    op.drop_table("projects")
    op.execute("DROP TYPE projectstatus")
```

Replace `backend/app/models_registry.py` with:

```python
"""Imports every ORM model so Base.metadata is complete for Alembic, tests,
and the API/worker processes (cross-module FKs resolve by table name)."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models
from app.modules.engagements import models as engagements_models
from app.modules.identity import models as identity_models
from app.modules.passport import models as passport_models

__all__ = [
    "audit_models",
    "engagements_models",
    "identity_models",
    "outbox_models",
    "passport_models",
]
```

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 2: Cross-module queries and test helper**

Append to `backend/app/modules/identity/accounts.py` (add imports `from collections.abc import Iterable`, `from sqlalchemy import select`, `from app.core.enums import AccountStatus` where missing):

```python
async def active_pm_ids(session: AsyncSession, user_ids: Iterable[UUID]) -> set[UUID]:
    """The subset of `user_ids` that are active project managers."""
    ids = list(user_ids)
    if not ids:
        return set()
    rows = await session.scalars(
        select(UserAccount.id).where(
            UserAccount.id.in_(ids),
            UserAccount.role == UserRole.PM,
            UserAccount.status == AccountStatus.ACTIVE,
        )
    )
    return set(rows.all())
```

In `backend/app/modules/identity/service.py`, add `active_pm_ids` to the `accounts` import and `has_permission` (from `app.modules.identity.permissions`) to the imports, and add both to `__all__`.

`backend/app/modules/passport/queries.py`:

```python
"""Read and status functions other modules use through passport.service."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.passport.models import Skill


async def existing_skill_ids(session: AsyncSession, skill_ids: Iterable[UUID]) -> set[UUID]:
    ids = list(skill_ids)
    if not ids:
        return set()
    return set((await session.scalars(select(Skill.id).where(Skill.id.in_(ids)))).all())
```

In `backend/app/modules/passport/service.py`, import `existing_skill_ids` from `app.modules.passport.queries` and add it to `__all__`.

Append to `backend/tests/support.py` (imports: `from app.core.time import utcnow` already present; add `from app.modules.engagements.models import Project, ProjectStaff`):

```python
async def make_project(
    session: AsyncSession,
    *,
    staff: list[UserAccount] | None = None,
    data_region: str = "GH",
    name: str = "Project Volta",
    required_skill_ids: list[UUID] | None = None,
) -> Project:
    project = Project(
        name=name, data_region=data_region, required_skill_ids=required_skill_ids or []
    )
    session.add(project)
    await session.flush()
    for user in staff or []:
        session.add(
            ProjectStaff(project_id=project.id, user_account_id=user.id, active_from=utcnow())
        )
    await session.commit()
    return project
```

- [ ] **Step 3: Write the failing tests**

`backend/tests/api/engagements/__init__.py`: empty file.

`backend/tests/api/engagements/test_projects.py`:

```python
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import Project
from app.modules.passport.models import Skill
from tests.support import bearer, make_project, make_user

URL = "/api/v1/projects"


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"name": "Project Volta", "data_region": "GH"}
    body.update(overrides)
    return body


async def test_pm_creates_a_project_and_is_staffed_on_it(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.commit()

    response = await client.post(
        URL,
        json=_body(client_name="Accra Water", required_skill_ids=[str(skill.id)]),
        headers=bearer(settings, pm),
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["name"], body["data_region"], body["status"]) == ("Project Volta", "GH", "active")
    assert body["staff_ids"] == [str(pm.id)]
    assert body["required_skill_ids"] == [str(skill.id)]
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id) == ("project.created", pm.id)


async def test_people_ops_project_starts_unstaffed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(URL, json=_body(), headers=bearer(settings, ops))

    assert response.json()["staff_ids"] == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"data_region": "ZZ"}, "unknown_data_region"),
        ({"required_skill_ids": [str(uuid4())]}, "unknown_skill"),
    ],
)
async def test_unknown_region_or_skill_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    overrides: dict[str, object],
    code: str,
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=_body(**overrides), headers=bearer(settings, pm))

    assert response.status_code == 400
    assert response.json()["code"] == code
    assert (await session.scalars(select(Project))).all() == []


@pytest.mark.parametrize(
    "overrides",
    [{"starts_on": "2026-11-01", "ends_on": "2026-10-01"}, {"name": ""}, {"data_region": "gh"}],
)
async def test_invalid_projects_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, overrides: dict[str, object]
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=_body(**overrides), headers=bearer(settings, pm))

    assert response.status_code == 422


@pytest.mark.parametrize("role", [UserRole.WORKER, UserRole.FINANCE])
async def test_only_staff_roles_create_projects(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    user = await make_user(session, role=role)

    response = await client.post(URL, json=_body(), headers=bearer(settings, user))

    assert response.status_code == 403


async def test_pm_lists_and_reads_only_projects_they_staff(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    mine = await make_project(session, staff=[pm], name="Mine")
    theirs = await make_project(session, name="Theirs")
    headers = bearer(settings, pm)

    listed = await client.get(URL, headers=headers)
    own = await client.get(f"{URL}/{mine.id}", headers=headers)
    other = await client.get(f"{URL}/{theirs.id}", headers=headers)

    assert [p["name"] for p in listed.json()] == ["Mine"]
    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json()["code"] == "project_not_found"


async def test_people_ops_sees_every_project(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await make_project(session, name="One")
    await make_project(session, name="Two")

    response = await client.get(URL, headers=bearer(settings, ops))

    assert sorted(p["name"] for p in response.json()) == ["One", "Two"]


async def test_workers_cannot_list_projects(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker = await make_user(session, role=UserRole.WORKER)

    response = await client.get(URL, headers=bearer(settings, worker))

    assert response.status_code == 403
```

`backend/tests/api/engagements/test_staffing.py`:

```python
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.models import ProjectStaff
from tests.support import bearer, make_project, make_user

Drain = Callable[[], Awaitable[None]]


def _url(project_id: object) -> str:
    return f"/api/v1/projects/{project_id}/staff"


async def _active_staff(session: AsyncSession, project_id: object) -> set[object]:
    rows = await session.scalars(
        select(ProjectStaff.user_account_id).where(
            ProjectStaff.project_id == project_id, ProjectStaff.active_to.is_(None)
        )
    )
    return set(rows.all())


async def test_people_ops_replaces_the_staff_list(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(kwame.id), str(kwame.id)]},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 200
    assert response.json()["staff_ids"] == [str(kwame.id)]
    assert await _active_staff(session, project.id) == {kwame.id}
    ended = (
        await session.scalars(select(ProjectStaff).where(ProjectStaff.user_account_id == ama.id))
    ).one()
    assert ended.active_to is not None
    audit = (await session.scalars(select(AuditLog))).one()
    assert audit.action == "project.staff_changed"
    assert (audit.before, audit.after) == ({"staff": [str(ama.id)]}, {"staff": [str(kwame.id)]})


async def test_staffed_pm_adds_a_colleague(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(ama.id), str(kwame.id)]},
        headers=bearer(settings, ama),
    )

    assert response.status_code == 200
    assert await _active_staff(session, project.id) == {ama.id, kwame.id}


async def test_unstaffed_pm_cannot_see_or_change_the_project(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    outsider = await make_user(session, role=UserRole.PM)
    project = await make_project(session)

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(outsider.id)]},
        headers=bearer(settings, outsider),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "project_not_found"


async def test_staff_must_be_active_pms(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    finance = await make_user(session, role=UserRole.FINANCE)
    project = await make_project(session)

    response = await client.put(
        _url(project.id),
        json={"user_account_ids": [str(finance.id)]},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "staff_not_active_pm"


async def test_unchanged_staff_list_writes_no_audit(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])

    await client.put(
        _url(project.id), json={"user_account_ids": [str(ama.id)]}, headers=bearer(settings, ama)
    )

    assert (await session.scalars(select(AuditLog))).all() == []


async def test_scim_deactivation_ends_the_pms_staffing(
    client: AsyncClient, session: AsyncSession, drain: Drain
) -> None:
    ama = await make_user(session, role=UserRole.PM, oidc_subject="kc-ama")
    project = await make_project(session, staff=[ama])

    await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
        headers={"Authorization": "Bearer scim-test-token", "Content-Type": "application/scim+json"},
    )
    await drain()

    assert await _active_staff(session, project.id) == set()
    removed = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "project.staff_removed"))
    ).one()
    assert (removed.target_id, removed.reason) == (project.id, "deactivated")
```

In `backend/tests/api/passport/test_invitations.py`, add:

```python
async def test_invitation_region_must_be_configured(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post(URL, json=BODY | {"data_region": "ZZ"}, headers=bearer(settings, pm))

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_data_region"
    assert (await session.scalars(select(Worker))).all() == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/api/engagements tests/api/passport/test_invitations.py -v`
Expected: FAIL — 404 for `/api/v1/projects` (no router) and the invitation region test returning 201.

- [ ] **Step 5: Implement**

`backend/app/modules/engagements/repository.py`:

```python
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.models import Project, ProjectStaff


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    def add(self, project: Project) -> Project:
        self.session.add(project)
        return project

    def add_staff(self, row: ProjectStaff) -> ProjectStaff:
        self.session.add(row)
        return row

    async def list_all(self) -> list[Project]:
        return list((await self.session.scalars(select(Project).order_by(Project.created_at))).all())

    async def list_staffed_by(self, user_id: UUID) -> list[Project]:
        stmt = (
            select(Project)
            .join(ProjectStaff, ProjectStaff.project_id == Project.id)
            .where(ProjectStaff.user_account_id == user_id, ProjectStaff.active_to.is_(None))
            .order_by(Project.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def is_staffed(self, project_id: UUID, user_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        ProjectStaff.project_id == project_id,
                        ProjectStaff.user_account_id == user_id,
                        ProjectStaff.active_to.is_(None),
                    )
                )
            )
        )

    async def active_staff_rows(self, project_id: UUID) -> list[ProjectStaff]:
        stmt = select(ProjectStaff).where(
            ProjectStaff.project_id == project_id, ProjectStaff.active_to.is_(None)
        )
        return list((await self.session.scalars(stmt)).all())

    async def active_staff_ids(self, project_id: UUID) -> set[UUID]:
        return {row.user_account_id for row in await self.active_staff_rows(project_id)}

    async def active_rows_for_user(self, user_id: UUID) -> list[ProjectStaff]:
        stmt = select(ProjectStaff).where(
            ProjectStaff.user_account_id == user_id, ProjectStaff.active_to.is_(None)
        )
        return list((await self.session.scalars(stmt)).all())
```

`backend/app/modules/engagements/schemas.py`:

```python
from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.engagements.enums import ProjectStatus


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    data_region: str = Field(pattern=r"^[A-Z]{2,8}$")
    required_skill_ids: list[UUID] = Field(default_factory=list, max_length=50)
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must not be before starts_on")
        return self


class ProjectRead(BaseModel):
    id: UUID
    name: str
    client_name: str | None
    data_region: str
    required_skill_ids: list[UUID]
    starts_on: date | None
    ends_on: date | None
    status: ProjectStatus
    staff_ids: list[UUID]
    created_at: datetime


class StaffAssignment(BaseModel):
    user_account_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("user_account_ids")
    @classmethod
    def _dedupe(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))
```

`backend/app/modules/engagements/projects.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import UserRole
from app.core.errors import BadRequest, Forbidden, NotFound
from app.core.time import utcnow
from app.modules.engagements.models import Project, ProjectStaff
from app.modules.engagements.repository import ProjectRepository
from app.modules.engagements.schemas import ProjectCreate, ProjectRead, StaffAssignment
from app.modules.identity.service import Permission, active_pm_ids, has_permission
from app.modules.passport.service import existing_skill_ids

_SEES_ALL = (UserRole.PEOPLE_OPS, UserRole.ADMIN)


class ProjectService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)

    async def create(self, actor: Actor, data: ProjectCreate) -> ProjectRead:
        if data.data_region not in self.settings.data_regions:
            raise BadRequest("Unknown data region", code="unknown_data_region")
        skill_ids = list(dict.fromkeys(data.required_skill_ids))
        if set(skill_ids) - await existing_skill_ids(self.session, skill_ids):
            raise BadRequest("Unknown skill id", code="unknown_skill")
        project = self.projects.add(
            Project(
                name=data.name.strip(),
                client_name=data.client_name,
                data_region=data.data_region,
                required_skill_ids=skill_ids,
                starts_on=data.starts_on,
                ends_on=data.ends_on,
                created_by_id=actor.user_id,
            )
        )
        await self.session.flush()
        if actor.role is UserRole.PM:
            self.projects.add_staff(
                ProjectStaff(project_id=project.id, user_account_id=actor.user_id, active_from=utcnow())
            )
            await self.session.flush()
        await write_audit(
            self.session,
            actor=actor,
            action="project.created",
            target_type="project",
            target_id=project.id,
            after={"name": project.name, "data_region": project.data_region},
        )
        return await self._read(project)

    async def _read(self, project: Project) -> ProjectRead:
        staff = await self.projects.active_staff_ids(project.id)
        return ProjectRead(
            id=project.id,
            name=project.name,
            client_name=project.client_name,
            data_region=project.data_region,
            required_skill_ids=project.required_skill_ids,
            starts_on=project.starts_on,
            ends_on=project.ends_on,
            status=project.status,
            staff_ids=sorted(staff, key=str),
            created_at=project.created_at,
        )

    async def visible(self, actor: Actor, project_id: UUID) -> Project:
        project = await self.projects.get(project_id)
        can_see = project is not None and (
            actor.role in _SEES_ALL
            or (
                actor.role is UserRole.PM
                and await self.projects.is_staffed(project.id, actor.user_id)
            )
        )
        if project is None or not can_see:
            raise NotFound("Project not found", code="project_not_found")
        return project

    async def read(self, actor: Actor, project_id: UUID) -> ProjectRead:
        return await self._read(await self.visible(actor, project_id))

    async def list_visible(self, actor: Actor) -> list[ProjectRead]:
        if actor.role in _SEES_ALL:
            projects = await self.projects.list_all()
        elif actor.role is UserRole.PM:
            projects = await self.projects.list_staffed_by(actor.user_id)
        else:
            raise Forbidden("Projects are visible to staff only", code="permission_denied")
        return [await self._read(p) for p in projects]

    async def set_staff(
        self, actor: Actor, project_id: UUID, data: StaffAssignment
    ) -> ProjectRead:
        project = await self.visible(actor, project_id)
        # visible() already restricts PMs to projects they staff.
        if not (
            has_permission(actor.role, Permission.PROJECT_STAFF_ASSIGN)
            or actor.role is UserRole.PM
        ):
            raise Forbidden("Missing permission project:staff_assign", code="permission_denied")
        wanted = set(data.user_account_ids)
        if wanted - await active_pm_ids(self.session, wanted):
            raise BadRequest("Staff must be active project managers", code="staff_not_active_pm")
        rows = await self.projects.active_staff_rows(project.id)
        current = {row.user_account_id: row for row in rows}
        now = utcnow()
        for user_id, row in current.items():
            if user_id not in wanted:
                row.active_to = now
        for user_id in wanted - current.keys():
            self.projects.add_staff(
                ProjectStaff(project_id=project.id, user_account_id=user_id, active_from=now)
            )
        await self.session.flush()
        before = sorted(str(u) for u in current)
        after = sorted(str(u) for u in wanted)
        if before != after:
            await write_audit(
                self.session,
                actor=actor,
                action="project.staff_changed",
                target_type="project",
                target_id=project.id,
                before={"staff": before},
                after={"staff": after},
            )
        return await self._read(project)


async def end_staffing_for(session: AsyncSession, user_id: UUID, *, reason: str) -> None:
    """A deactivated or re-roled account stops staffing every project (spec §7.6)."""
    now = utcnow()
    for row in await ProjectRepository(session).active_rows_for_user(user_id):
        row.active_to = now
        await write_audit(
            session,
            actor=None,
            action="project.staff_removed",
            target_type="project",
            target_id=row.project_id,
            before={"staff_member": str(user_id)},
            reason=reason,
        )
```

`backend/app/modules/engagements/handlers.py`:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.projects import end_staffing_for
from app.modules.identity.schemas import AccessRevoked


def register(registry: HandlerRegistry) -> None:
    async def end_staffing(session: AsyncSession, payload: dict[str, Any]) -> None:
        await end_staffing_for(
            session, UUID(payload["aggregate_id"]), reason=payload.get("reason", "access_revoked")
        )

    registry.register(AccessRevoked, "engagements.end_staffing_on_revocation", end_staffing)
```

`backend/app/modules/engagements/router.py`:

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.modules.engagements.projects import ProjectService
from app.modules.engagements.schemas import ProjectCreate, ProjectRead, StaffAssignment
from app.modules.identity.service import CurrentActor, Permission, require_permission

router = APIRouter(prefix="/api/v1", tags=["engagements"])

ProjectManager = Annotated[Actor, Depends(require_permission(Permission.PROJECT_MANAGE))]


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate, actor: ProjectManager, session: SessionDep, settings: SettingsDep
) -> ProjectRead:
    return await ProjectService(session, settings).create(actor, body)


@router.get("/projects")
async def list_projects(
    actor: CurrentActor, session: SessionDep, settings: SettingsDep
) -> list[ProjectRead]:
    return await ProjectService(session, settings).list_visible(actor)


@router.get("/projects/{project_id}")
async def read_project(
    project_id: UUID, actor: CurrentActor, session: SessionDep, settings: SettingsDep
) -> ProjectRead:
    return await ProjectService(session, settings).read(actor, project_id)


@router.put("/projects/{project_id}/staff")
async def set_project_staff(
    project_id: UUID,
    body: StaffAssignment,
    actor: CurrentActor,
    session: SessionDep,
    settings: SettingsDep,
) -> ProjectRead:
    return await ProjectService(session, settings).set_staff(actor, project_id, body)
```

`backend/app/modules/engagements/service.py`:

```python
"""Public interface of the engagements module."""

from app.modules.engagements.enums import EngagementPath, EngagementStatus, ProjectStatus, WorkMode

__all__ = ["EngagementPath", "EngagementStatus", "ProjectStatus", "WorkMode"]
```

In `backend/app/wiring.py`, import `from app.modules.engagements import handlers as engagements_handlers` and add `engagements_handlers.register(registry)` inside `build_registry`, after the identity registration.

In `backend/app/main.py`, import `from app.modules.engagements.router import router as engagements_router` and add `app.include_router(engagements_router)` after the passport router.

Invitation region validation — in `backend/app/modules/passport/invitations.py`:
- `InvitationService.__init__(self, session: AsyncSession, settings: Settings)`; store `self.settings` (import `Settings` from `app.core.config`, `BadRequest` from `app.core.errors`).
- At the top of `invite`, before the resend check:

```python
        if data.data_region not in self.settings.data_regions:
            raise BadRequest("Unknown data region", code="unknown_data_region")
```

In `backend/app/modules/passport/router.py`, add `settings: SettingsDep` (from `app.core.deps`) to `invite_worker` and construct `InvitationService(session, settings)`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/api/engagements tests/api/passport/test_invitations.py -v`
Expected: all pass.

- [ ] **Step 7: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(engagements): projects and staffing; regions validated for projects and invitations"
```

---

### Task 2: Engagement and feedback schema, history, PM visibility sources

**Files:**
- Create: `backend/alembic/versions/0007_engagements.py`, `backend/app/modules/engagements/visibility.py`
- Modify: `backend/app/modules/engagements/models.py`, `repository.py`, `schemas.py`, `router.py`, `service.py`; `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/schemas.py`, `backend/app/modules/passport/service.py`; `backend/app/wiring.py`; `backend/tests/support.py`
- Test: `backend/tests/api/engagements/test_visibility_sources.py`, `backend/tests/api/engagements/test_history.py`

**Interfaces:**
- Consumes: `ProjectRepository` (Task 1); `Visibility`, `require_visibility`, `VisibilitySource` (identity.service); `ConsentRepository`, `WorkerRepository`.
- Produces:
  - Models `Engagement`, `Feedback`; `EngagementRepository(session)` with `get`, `get_for_update`, `add`, `add_feedback`, `list_for_worker(worker_id)`, `feedback_for(engagement_ids) -> dict[UUID, Feedback]`, `worker_engaged_on(worker_id, project_ids) -> bool`.
  - Schemas `ContractTerms(scope, access_notes)`, `FeedbackRead`, `EngagementRead`; function `engagement_read(engagement, feedback) -> EngagementRead` in `schemas.py`.
  - Passport: `WorkerRegion(data_region, cross_region_ok)` schema; `queries.worker_region(session, worker_id) -> WorkerRegion | None` (None for unknown, offboarded or anonymized workers), exported from `passport.service`.
  - Visibility source `project_relationship(session, actor, worker_id) -> Visibility`, exported from `engagements.service` and registered in `app.wiring.visibility_sources()`.
  - Route `GET /api/v1/workers/{worker_id}/engagements` (guard `DETAIL`) → `list[EngagementRead]`, newest first.
  - Test helpers `make_engagement(...)`.

The PM visibility rule (spec §7.1): a PM gets **detail** on a worker who has any engagement on a project the PM actively staffs; otherwise **summary** if the PM actively staffs a project in the worker's data region, or the worker has granted `cross_region_matching` consent; otherwise nothing. Staffing is read live, so ending a staff row removes the visibility at once.

- [ ] **Step 1: Models and migration**

Append to `backend/app/modules/engagements/models.py` (extend the imports with `Boolean, Numeric, Text` from sqlalchemy, `JSONB` from the postgresql dialect, `Decimal` from decimal, `Any` from typing, and the enums `EngagementPath, EngagementStatus, WorkMode`):

```python
class Engagement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagements"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    path: Mapped[EngagementPath] = mapped_column(pg_enum(EngagementPath), nullable=False)
    status: Mapped[EngagementStatus] = mapped_column(
        pg_enum(EngagementStatus),
        default=EngagementStatus.PENDING_SIGNATURE,
        server_default=EngagementStatus.PENDING_SIGNATURE.value,
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    work_mode: Mapped[WorkMode] = mapped_column(pg_enum(WorkMode), nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    contract_terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prefilled_from_engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contract_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billable_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payroll_signaled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stuck_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    esign_envelope_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_engagements_worker_start", "worker_id", "start_date"),
        Index("ix_engagements_project", "project_id"),
        Index(
            "ix_engagements_in_flight",
            "status",
            postgresql_where=text("status IN ('pending_signature','awaiting_signature')"),
        ),
        Index(
            "uq_engagements_open_worker_project",
            "worker_id",
            "project_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_signature','awaiting_signature','signed','active')"
            ),
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        CheckConstraint("rate > 0", name="rate_positive"),
    )


class Feedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    structured_answers: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False)
    free_text: Mapped[str | None] = mapped_column(Text)
    skill_ids_demonstrated: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("'{}'"), nullable=False
    )
    excluded_from_standing: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
```

`backend/alembic/versions/0007_engagements.py`:

```python
"""engagements: engagements and feedback

Revision ID: 0007_engagements
Revises: 0006_projects
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_engagements"
down_revision: str | None = "0006_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column[object]:
    return sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    op.create_table(
        "engagements",
        _id(),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column(
            "path", sa.Enum("first_time", "reactivation", name="engagementpath"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending_signature", "awaiting_signature", "signed", "active", "completed",
                "cancelled", name="engagementstatus",
            ),
            server_default="pending_signature",
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "work_mode", sa.Enum("remote", "onsite", "hybrid", name="workmode"), nullable=False
        ),
        sa.Column("location", sa.String(120), nullable=True),
        sa.Column("contract_terms", postgresql.JSONB(), nullable=False),
        sa.Column("prefilled_from_engagement_id", _UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        _ts("contract_sent_at"),
        _ts("signed_at"),
        _ts("billable_start_at"),
        _ts("completed_at"),
        _ts("payroll_signaled_at"),
        _ts("stuck_flagged_at"),
        sa.Column("esign_envelope_id", sa.String(120), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("created_by_id", _UUID, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_engagements"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_engagements_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_engagements_project_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["prefilled_from_engagement_id"], ["engagements.id"],
            name="fk_engagements_prefilled_from_engagement_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["user_accounts.id"], name="fk_engagements_created_by_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("esign_envelope_id", name="uq_engagements_esign_envelope_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_engagements_idempotency_key"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name=op.f("ck_engagements_dates_ordered")
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_engagements_rate_positive")),
    )
    op.create_index("ix_engagements_worker_start", "engagements", ["worker_id", "start_date"])
    op.create_index("ix_engagements_project", "engagements", ["project_id"])
    op.create_index(
        "ix_engagements_in_flight",
        "engagements",
        ["status"],
        postgresql_where=sa.text("status IN ('pending_signature','awaiting_signature')"),
    )
    op.create_index(
        "uq_engagements_open_worker_project",
        "engagements",
        ["worker_id", "project_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_signature','awaiting_signature','signed','active')"
        ),
    )

    op.create_table(
        "feedback",
        _id(),
        sa.Column("engagement_id", _UUID, nullable=False),
        sa.Column("reviewer_id", _UUID, nullable=True),
        sa.Column("structured_answers", postgresql.JSONB(), nullable=False),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column(
            "skill_ids_demonstrated",
            postgresql.ARRAY(_UUID),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "excluded_from_standing", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name="fk_feedback_engagement_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["user_accounts.id"], name="fk_feedback_reviewer_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("engagement_id", name="uq_feedback_engagement_id"),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_index("uq_engagements_open_worker_project", table_name="engagements")
    op.drop_index("ix_engagements_in_flight", table_name="engagements")
    op.drop_index("ix_engagements_project", table_name="engagements")
    op.drop_index("ix_engagements_worker_start", table_name="engagements")
    op.drop_table("engagements")
    for enum_name in ("workmode", "engagementstatus", "engagementpath"):
        op.execute(f"DROP TYPE {enum_name}")
```

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all pass.

- [ ] **Step 2: Test helpers**

Append to `backend/tests/support.py` (imports: `from datetime import date`, `from decimal import Decimal`, `from sqlalchemy import select` if missing, `from app.modules.engagements.enums import EngagementPath, EngagementStatus, WorkMode`, `from app.modules.engagements.models import Engagement`, `from app.modules.passport.models import Skill, SkillClaim`):

```python
async def make_ready_worker(
    session: AsyncSession,
    *,
    email: str | None = None,
    data_region: str = "GH",
    full_name: str = "Kofi Mensah",
) -> tuple[Worker, UserAccount]:
    """A worker who can be engaged: onboarding complete, location, a language
    and one skill claim (data-analysis)."""
    worker, account = await make_worker(
        session, email=email, data_region=data_region, full_name=full_name
    )
    worker.base_location = "Accra"
    worker.languages = ["en"]
    skill = await session.scalar(select(Skill).where(Skill.slug == "data-analysis"))
    if skill is None:
        skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
        session.add(skill)
        await session.flush()
    session.add(SkillClaim(worker_id=worker.id, skill_id=skill.id))
    await session.commit()
    return worker, account


async def make_engagement(
    session: AsyncSession,
    *,
    worker_id: UUID,
    project_id: UUID,
    status: EngagementStatus = EngagementStatus.COMPLETED,
    path: EngagementPath = EngagementPath.FIRST_TIME,
    start_date: date = date(2026, 1, 5),
    end_date: date | None = None,
    rate: Decimal = Decimal("450.00"),
    currency: str = "GHS",
    work_mode: WorkMode = WorkMode.REMOTE,
    scope: str = "Build the data pipeline",
) -> Engagement:
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
    )
    session.add(engagement)
    await session.commit()
    return engagement
```

- [ ] **Step 3: Write the failing tests**

`backend/tests/api/engagements/test_visibility_sources.py`:

```python
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.models import ProjectStaff
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import ConsentPurpose, WorkerStatus
from app.modules.passport.models import Consent
from tests.support import bearer, make_engagement, make_project, make_user, make_worker


async def _view(
    client: AsyncClient, settings: Settings, pm: UserAccount, worker_id: UUID
) -> str | None:
    response = await client.get(f"/api/v1/workers/{worker_id}", headers=bearer(settings, pm))
    return response.json().get("view") if response.status_code == 200 else None


async def test_pm_on_a_project_in_the_workers_region_sees_the_summary(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH")

    assert await _view(client, settings, pm, worker.id) == "summary"


async def test_other_region_needs_cross_region_consent(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="EU")
    worker, _ = await make_worker(session, data_region="GH")

    before = await _view(client, settings, pm, worker.id)
    session.add(
        Consent(
            worker_id=worker.id,
            purpose=ConsentPurpose.CROSS_REGION_MATCHING,
            granted=True,
            legal_basis="consent",
            granted_at=utcnow(),
        )
    )
    await session.commit()
    after = await _view(client, settings, pm, worker.id)

    assert (before, after) == (None, "summary")


async def test_engagement_on_a_staffed_project_gives_detail(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="EU")
    worker, _ = await make_worker(session, data_region="GH")
    await make_engagement(session, worker_id=worker.id, project_id=project.id)

    assert await _view(client, settings, pm, worker.id) == "detail"


async def test_ended_staffing_removes_visibility_immediately(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH")
    await make_engagement(session, worker_id=worker.id, project_id=project.id)
    await session.execute(update(ProjectStaff).values(active_to=utcnow()))
    await session.commit()

    assert await _view(client, settings, pm, worker.id) is None


@pytest.mark.parametrize("status", [WorkerStatus.ANONYMIZED, WorkerStatus.OFFBOARDED])
async def test_offboarded_or_anonymized_workers_are_not_surfaced_by_region(
    client: AsyncClient, session: AsyncSession, settings: Settings, status: WorkerStatus
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH", status=status)

    assert await _view(client, settings, pm, worker.id) is None


async def test_unstaffed_pm_sees_nothing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_worker(session, data_region="GH")

    assert await _view(client, settings, pm, worker.id) is None
```

`backend/tests/api/engagements/test_history.py`:

```python
from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Feedback
from tests.support import bearer, make_engagement, make_project, make_user, make_worker


def _url(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/engagements"


async def test_worker_sees_their_history_newest_first_with_feedback(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)
    project = await make_project(session)
    older = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, start_date=date(2025, 3, 1)
    )
    newer = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        start_date=date(2026, 2, 1),
        status=EngagementStatus.CANCELLED,
    )
    session.add(
        Feedback(
            engagement_id=older.id,
            structured_answers={
                "delivered_on_agreed_dates": True,
                "handled_scope_changes_without_escalation": True,
                "would_reengage": True,
            },
            free_text="Great work on the pipeline.",
        )
    )
    await session.commit()

    response = await client.get(_url(worker.id), headers=bearer(settings, account))

    body = response.json()
    assert [e["id"] for e in body] == [str(newer.id), str(older.id)]
    assert body[1]["rate"] == "450.00"
    assert body[1]["contract_terms"]["scope"] == "Build the data pipeline"
    assert body[1]["feedback"]["free_text"] == "Great work on the pipeline."
    assert body[0]["feedback"] is None
    assert body[0]["stuck"] is False


async def test_people_ops_sees_any_workers_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    worker, _ = await make_worker(session)
    await make_engagement(session, worker_id=worker.id, project_id=(await make_project(session)).id)

    response = await client.get(_url(worker.id), headers=bearer(settings, ops))

    assert len(response.json()) == 1


async def test_summary_level_pm_cannot_read_history(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    worker, _ = await make_worker(session, data_region="GH")
    await make_engagement(session, worker_id=worker.id, project_id=(await make_project(session)).id)

    response = await client.get(_url(worker.id), headers=bearer(settings, pm))

    assert response.status_code == 404
    assert response.json()["code"] == "worker_not_found"
```

(ruff will move `from datetime import date` into the import block.)

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/api/engagements/test_visibility_sources.py tests/api/engagements/test_history.py -v`
Expected: FAIL — summary/detail tests get 404 (no visibility source) and the history route returns 404/405.

- [ ] **Step 5: Implement**

Append to `backend/app/modules/passport/schemas.py`:

```python
class WorkerRegion(BaseModel):
    data_region: str
    cross_region_ok: bool
```

Append to `backend/app/modules/passport/queries.py` (imports: `WorkerStatus, ConsentPurpose` from passport enums; `ConsentRepository, WorkerRepository` from passport repository; `WorkerRegion` from passport schemas):

```python
_NOT_SURFACED = (WorkerStatus.OFFBOARDED, WorkerStatus.ANONYMIZED)


async def worker_region(session: AsyncSession, worker_id: UUID) -> WorkerRegion | None:
    """Region facts for visibility and matching; None if the worker is
    unknown or no longer part of the talent pool."""
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status in _NOT_SURFACED:
        return None
    consent = await ConsentRepository(session).get(
        worker_id, ConsentPurpose.CROSS_REGION_MATCHING
    )
    return WorkerRegion(
        data_region=worker.data_region,
        cross_region_ok=consent is not None and consent.granted,
    )
```

Export `worker_region` from `backend/app/modules/passport/service.py`.

Append to `backend/app/modules/engagements/repository.py` (imports: `Engagement, Feedback` models, `Sequence` from collections.abc):

```python
class EngagementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, engagement_id: UUID) -> Engagement | None:
        return await self.session.get(Engagement, engagement_id)

    async def get_for_update(self, engagement_id: UUID) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(Engagement.id == engagement_id).with_for_update()
        )

    def add(self, engagement: Engagement) -> Engagement:
        self.session.add(engagement)
        return engagement

    def add_feedback(self, feedback: Feedback) -> Feedback:
        self.session.add(feedback)
        return feedback

    async def list_for_worker(self, worker_id: UUID) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(Engagement.worker_id == worker_id)
            .order_by(Engagement.start_date.desc(), Engagement.created_at.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def feedback_for(self, engagement_ids: Sequence[UUID]) -> dict[UUID, Feedback]:
        if not engagement_ids:
            return {}
        rows = await self.session.scalars(
            select(Feedback).where(Feedback.engagement_id.in_(engagement_ids))
        )
        return {f.engagement_id: f for f in rows.all()}

    async def worker_engaged_on(self, worker_id: UUID, project_ids: Sequence[UUID]) -> bool:
        if not project_ids:
            return False
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        Engagement.worker_id == worker_id,
                        Engagement.project_id.in_(project_ids),
                    )
                )
            )
        )
```

Append to `backend/app/modules/engagements/schemas.py` (imports: `Decimal`, `EngagementPath, EngagementStatus, WorkMode`, and the `Engagement, Feedback` models):

```python
class ContractTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(min_length=1, max_length=2000)
    access_notes: str | None = Field(default=None, max_length=2000)


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    structured_answers: dict[str, bool]
    free_text: str | None
    skill_ids_demonstrated: list[UUID]
    reviewer_id: UUID | None
    created_at: datetime


class EngagementRead(BaseModel):
    id: UUID
    worker_id: UUID
    project_id: UUID
    path: EngagementPath
    status: EngagementStatus
    start_date: date
    end_date: date | None
    rate: Decimal
    currency: str
    work_mode: WorkMode
    location: str | None
    contract_terms: ContractTerms
    prefilled_from_engagement_id: UUID | None
    confirmed_at: datetime
    contract_sent_at: datetime | None
    signed_at: datetime | None
    billable_start_at: datetime | None
    completed_at: datetime | None
    stuck: bool
    feedback: FeedbackRead | None


def engagement_read(engagement: Engagement, feedback: Feedback | None) -> EngagementRead:
    return EngagementRead(
        id=engagement.id,
        worker_id=engagement.worker_id,
        project_id=engagement.project_id,
        path=engagement.path,
        status=engagement.status,
        start_date=engagement.start_date,
        end_date=engagement.end_date,
        rate=engagement.rate,
        currency=engagement.currency,
        work_mode=engagement.work_mode,
        location=engagement.location,
        contract_terms=ContractTerms.model_validate(engagement.contract_terms),
        prefilled_from_engagement_id=engagement.prefilled_from_engagement_id,
        confirmed_at=engagement.confirmed_at,
        contract_sent_at=engagement.contract_sent_at,
        signed_at=engagement.signed_at,
        billable_start_at=engagement.billable_start_at,
        completed_at=engagement.completed_at,
        stuck=engagement.stuck_flagged_at is not None,
        feedback=FeedbackRead.model_validate(feedback) if feedback is not None else None,
    )
```

`backend/app/modules/engagements/visibility.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.enums import UserRole
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.identity.service import Visibility
from app.modules.passport.service import worker_region


async def project_relationship(
    session: AsyncSession, actor: Actor, worker_id: UUID
) -> Visibility:
    """Spec §7.1 for PMs: detail through an engagement on a project they staff,
    summary through a staffed project the worker is region-eligible for."""
    if actor.role is not UserRole.PM:
        return Visibility.NONE
    staffed = await ProjectRepository(session).list_staffed_by(actor.user_id)
    if not staffed:
        return Visibility.NONE
    if await EngagementRepository(session).worker_engaged_on(worker_id, [p.id for p in staffed]):
        return Visibility.DETAIL
    region = await worker_region(session, worker_id)
    if region is None:
        return Visibility.NONE
    if region.cross_region_ok or any(p.data_region == region.data_region for p in staffed):
        return Visibility.SUMMARY
    return Visibility.NONE
```

Replace `backend/app/modules/engagements/service.py` with:

```python
"""Public interface of the engagements module."""

from app.modules.engagements.enums import EngagementPath, EngagementStatus, ProjectStatus, WorkMode
from app.modules.engagements.visibility import project_relationship

__all__ = [
    "EngagementPath",
    "EngagementStatus",
    "ProjectStatus",
    "WorkMode",
    "project_relationship",
]
```

In `backend/app/wiring.py`, change `visibility_sources` to:

```python
def visibility_sources() -> list[VisibilitySource]:
    return [project_relationship]
```

with `from app.modules.engagements.service import project_relationship`.

Add to `backend/app/modules/engagements/router.py` (imports: `Visibility, require_visibility` from identity.service; `EngagementRepository`; `EngagementRead, engagement_read`):

```python
@router.get("/workers/{worker_id}/engagements")
async def list_worker_engagements(
    worker_id: UUID,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> list[EngagementRead]:
    repo = EngagementRepository(session)
    engagements = await repo.list_for_worker(worker_id)
    feedback = await repo.feedback_for([e.id for e in engagements])
    return [engagement_read(e, feedback.get(e.id)) for e in engagements]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/api/engagements tests/api/passport tests/api/test_visibility_guard.py -v`
Expected: all pass.

- [ ] **Step 7: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add alembic app tests
git commit -m "feat(engagements): engagement and feedback schema, history, PM visibility sources"
```

---

### Task 3: First-time engagements

**Files:**
- Create: `backend/app/core/db/errors.py`, `backend/app/modules/engagements/engagements.py`
- Modify: `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/schemas.py`, `backend/app/modules/passport/service.py`, `backend/app/modules/passport/profile.py`, `backend/app/modules/engagements/repository.py`, `schemas.py`, `router.py`; `backend/tests/support.py`
- Test: `backend/tests/integration/test_db_errors.py`, `backend/tests/api/engagements/test_first_time.py`

**Interfaces:**
- Consumes: `ProjectRepository`, `EngagementRepository`, `worker_region` (Task 2).
- Produces:
  - `app.core.db.errors.violated_constraint(exc: IntegrityError) -> str | None`.
  - Passport: `queries.profile_gaps(session, worker) -> list[str]` (used by onboarding and engagements); `EngagementReadiness(onboarding_complete: bool, gaps: list[str])`; `queries.engagement_readiness(session, worker_id) -> EngagementReadiness | None`; both exported from `passport.service`.
  - `EngagementRepository.has_history(worker_id) -> bool` (any non-cancelled engagement), `open_for(worker_id, project_id) -> Engagement | None`.
  - Schemas `EngagementCreate` (extra forbidden); events `EngagementCreated(aggregate_id, worker_id, project_id, path)` with `event_type = "engagements.engagement_created"`.
  - `EngagementService(session)`: `create(actor, worker_id, data, *, path, idempotency_key=None, prefilled_from=None) -> Engagement`.
  - Route `POST /api/v1/workers/{worker_id}/engagements` (201; permission `ENGAGEMENT_CREATE`; guard `SUMMARY`).
  - Error codes `project_not_found` (404), `project_closed` (409), `worker_not_ready` (409), `region_not_eligible` (409), `use_reactivation` (409), `no_prior_engagement` (409), `engagement_already_open` (409), `idempotency_key_reused` (409).
  - Test helper `engagement_terms(project_id, **overrides) -> dict[str, object]`.

Rules for creating any engagement (spec §7.2, FR-5.1, FR-4.3): the PM must be actively staffed on the project; the project must be active; the worker must have completed onboarding **and** still have a location, a language and a skill (carry-forward); the worker must be in the project's region or have granted cross-region consent; there is at most one open engagement per worker per project. The path follows history: a worker with no non-cancelled engagement gets `first_time`; anyone else must be reactivated (Task 4).

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_db_errors.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.errors import violated_constraint
from app.core.enums import AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from tests.support import make_user


async def test_reports_the_violated_constraint_name(session: AsyncSession) -> None:
    await make_user(session, role=UserRole.PM, email="ama@bonarda.works")
    session.add(
        UserAccount(
            email="ama@bonarda.works", role=UserRole.PM, auth_provider=AuthProvider.CORPORATE_SSO
        )
    )

    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()

    assert violated_constraint(excinfo.value) == "uq_user_accounts_email"
```

Append to `backend/tests/support.py` (import `datetime.date` if missing):

```python
def engagement_terms(project_id: UUID, **overrides: object) -> dict[str, object]:
    terms: dict[str, object] = {
        "project_id": str(project_id),
        "start_date": utcnow().date().isoformat(),
        "rate": "450.00",
        "currency": "GHS",
        "work_mode": "remote",
        "location": None,
        "contract_terms": {"scope": "Build the data pipeline", "access_notes": "VPN and repo"},
    }
    terms.update(overrides)
    return terms
```

`backend/tests/api/engagements/test_first_time.py`:

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
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.passport.enums import OnboardingState
from app.modules.passport.models import SkillClaim
from tests.support import (
    bearer,
    engagement_terms,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    make_worker,
)


def _url(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/engagements"


async def test_pm_engages_a_first_time_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["path"], body["status"]) == ("first_time", "pending_signature")
    assert body["confirmed_at"] is not None
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "engagements.engagement_created"
    assert event.payload == {
        "aggregate_id": body["id"],
        "worker_id": str(worker.id),
        "project_id": str(project.id),
        "path": "first_time",
    }
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.actor_id) == ("engagement.created", pm.id)


async def test_project_must_be_staffed_by_the_pm(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm])
    other = await make_project(session, name="Other")
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(other.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "project_not_found"


async def test_invited_worker_is_not_ready(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_worker(session, onboarding_state=OnboardingState.INVITED)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "worker_not_ready"


async def test_worker_who_removed_their_last_skill_is_not_ready(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    for claim in (await session.scalars(select(SkillClaim))).all():
        await session.delete(claim)
    await session.commit()

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.json()["code"] == "worker_not_ready"
    assert "skills" in response.json()["detail"]


async def test_worker_outside_the_projects_region_is_not_eligible(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    await make_project(session, staff=[pm], data_region="GH")
    eu_project = await make_project(session, staff=[pm], data_region="EU", name="EU")
    worker, _ = await make_ready_worker(session, data_region="GH")

    response = await client.post(
        _url(worker.id), json=engagement_terms(eu_project.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "region_not_eligible"


async def test_worker_with_history_must_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    await make_engagement(session, worker_id=worker.id, project_id=(await make_project(session)).id)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.json()["code"] == "use_reactivation"


async def test_cancelled_history_does_not_count(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session)).id,
        status=EngagementStatus.CANCELLED,
    )

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, pm)
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"rate": "0"},
        {"currency": "ghs"},
        {"end_date": "2020-01-01"},
        {"work_mode": "moon"},
        {"worker_id": str(uuid4())},
        {"contract_terms": {"scope": ""}},
    ],
)
async def test_invalid_terms_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings, overrides: dict[str, object]
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id, **overrides), headers=bearer(settings, pm)
    )

    assert response.status_code == 422
    assert (await session.scalars(select(Engagement))).all() == []


async def test_people_ops_cannot_engage(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    project = await make_project(session)
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _url(worker.id), json=engagement_terms(project.id), headers=bearer(settings, ops)
    )

    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_db_errors.py tests/api/engagements/test_first_time.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.db.errors'` and 405 for the engagement route.

- [ ] **Step 3: Implement**

`backend/app/core/db/errors.py`:

```python
from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint an asyncpg integrity error violated, so callers
    map exactly the violation they expect and re-raise everything else."""
    cause = getattr(exc.orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    return str(name) if name else None
```

Append to `backend/app/modules/passport/schemas.py`:

```python
class EngagementReadiness(BaseModel):
    onboarding_complete: bool
    gaps: list[str]
```

Append to `backend/app/modules/passport/queries.py` (imports: `OnboardingState`; `SkillClaimRepository`; `Worker` model; `EngagementReadiness`):

```python
async def profile_gaps(session: AsyncSession, worker: Worker) -> list[str]:
    """What a worker still needs before they can be engaged (FR-5.1)."""
    gaps = []
    if not worker.base_location:
        gaps.append("base_location")
    if not worker.languages:
        gaps.append("languages")
    if not await SkillClaimRepository(session).list_for_worker(worker.id):
        gaps.append("skills")
    return gaps


async def engagement_readiness(
    session: AsyncSession, worker_id: UUID
) -> EngagementReadiness | None:
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status in _NOT_SURFACED:
        return None
    return EngagementReadiness(
        onboarding_complete=worker.onboarding_state is OnboardingState.PROFILE_COMPLETE,
        gaps=await profile_gaps(session, worker),
    )
```

Export `profile_gaps` and `engagement_readiness` from `passport/service.py` (`EngagementReadiness` is reached through `passport.schemas`).

In `backend/app/modules/passport/profile.py`, inside `complete_onboarding`, replace the three inline `missing.append(...)` checks with `missing = await profile_gaps(self.session, worker)` (import from `app.modules.passport.queries`).

Append to `backend/app/modules/engagements/repository.py` `EngagementRepository` (import `OPEN_STATUSES, EngagementStatus`):

```python
    async def has_history(self, worker_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        Engagement.worker_id == worker_id,
                        Engagement.status != EngagementStatus.CANCELLED,
                    )
                )
            )
        )

    async def open_for(self, worker_id: UUID, project_id: UUID) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(
                Engagement.worker_id == worker_id,
                Engagement.project_id == project_id,
                Engagement.status.in_(OPEN_STATUSES),
            )
        )
```

Append to `backend/app/modules/engagements/schemas.py` (imports: `ClassVar`, `DomainEvent`):

```python
class EngagementCreate(BaseModel):
    """Terms a PM confirms (FR-4.3/4.4). Workers are addressed in the path."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    start_date: date
    end_date: date | None = None
    rate: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    work_mode: WorkMode
    location: str | None = Field(default=None, max_length=120)
    contract_terms: ContractTerms

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class EngagementCreated(DomainEvent):
    event_type: ClassVar[str] = "engagements.engagement_created"
    worker_id: UUID
    project_id: UUID
    path: EngagementPath
```

`backend/app/modules/engagements/engagements.py`:

```python
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementPath, EngagementStatus, ProjectStatus
from app.modules.engagements.models import Engagement, Project
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.engagements.schemas import EngagementCreate, EngagementCreated
from app.modules.passport.service import engagement_readiness, worker_region

_CONSTRAINT_CODES = {
    "uq_engagements_open_worker_project": (
        "This worker already has an open engagement on this project",
        "engagement_already_open",
    ),
    "uq_engagements_idempotency_key": (
        "This Idempotency-Key was already used for a different request",
        "idempotency_key_reused",
    ),
}


class EngagementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.engagements = EngagementRepository(session)

    async def staffed_project(self, actor: Actor, project_id: UUID) -> Project:
        project = await self.projects.get(project_id)
        if project is None or not await self.projects.is_staffed(project.id, actor.user_id):
            raise NotFound("Project not found", code="project_not_found")
        return project

    async def create(
        self,
        actor: Actor,
        worker_id: UUID,
        data: EngagementCreate,
        *,
        path: EngagementPath,
        idempotency_key: str | None = None,
        prefilled_from: UUID | None = None,
    ) -> Engagement:
        project = await self.staffed_project(actor, data.project_id)
        if project.status is not ProjectStatus.ACTIVE:
            raise Conflict("This project is closed", code="project_closed")
        readiness = await engagement_readiness(self.session, worker_id)
        if readiness is None:
            raise NotFound("Worker not found", code="worker_not_found")
        if not readiness.onboarding_complete or readiness.gaps:
            missing = ", ".join(readiness.gaps) or "onboarding"
            raise Conflict(f"Worker profile incomplete: {missing}", code="worker_not_ready")
        region = await worker_region(self.session, worker_id)
        if region is None or not (
            region.cross_region_ok or region.data_region == project.data_region
        ):
            raise Conflict(
                "Worker is not eligible for this project's region", code="region_not_eligible"
            )
        has_history = await self.engagements.has_history(worker_id)
        if path is EngagementPath.FIRST_TIME and has_history:
            raise Conflict(
                "This worker has engaged with Bonarda before; reactivate them instead",
                code="use_reactivation",
            )
        if path is EngagementPath.REACTIVATION and not has_history:
            raise Conflict("No earlier engagement to reactivate", code="no_prior_engagement")
        if await self.engagements.open_for(worker_id, project.id) is not None:
            raise Conflict(*_CONSTRAINT_CODES["uq_engagements_open_worker_project"])
        try:
            async with self.session.begin_nested():
                engagement = self.engagements.add(
                    Engagement(
                        worker_id=worker_id,
                        project_id=project.id,
                        path=path,
                        status=EngagementStatus.PENDING_SIGNATURE,
                        start_date=data.start_date,
                        end_date=data.end_date,
                        rate=data.rate,
                        currency=data.currency,
                        work_mode=data.work_mode,
                        location=data.location,
                        contract_terms=data.contract_terms.model_dump(),
                        prefilled_from_engagement_id=prefilled_from,
                        confirmed_at=utcnow(),
                        idempotency_key=idempotency_key,
                        created_by_id=actor.user_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            mapped = _CONSTRAINT_CODES.get(violated_constraint(exc) or "")
            if mapped is None:
                raise
            raise Conflict(mapped[0], code=mapped[1]) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="engagement.created",
            target_type="engagement",
            target_id=engagement.id,
            after={
                "path": path.value,
                "project_id": str(project.id),
                "start_date": engagement.start_date.isoformat(),
            },
        )
        await emit_event(
            self.session,
            EngagementCreated(
                aggregate_id=engagement.id,
                worker_id=worker_id,
                project_id=project.id,
                path=path,
            ),
        )
        return engagement
```

Add to `backend/app/modules/engagements/router.py` (imports: `EngagementCreate`, `EngagementPath`, `EngagementService`):

```python
EngagementCreator = Annotated[Actor, Depends(require_permission(Permission.ENGAGEMENT_CREATE))]


@router.post("/workers/{worker_id}/engagements", status_code=201)
async def create_first_time_engagement(
    worker_id: UUID,
    body: EngagementCreate,
    actor: EngagementCreator,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> EngagementRead:
    engagement = await EngagementService(session).create(
        actor, worker_id, body, path=EngagementPath.FIRST_TIME
    )
    return engagement_read(engagement, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_db_errors.py tests/api/engagements tests/api/passport -v`
Expected: all pass (including the onboarding tests, which now use `profile_gaps`).

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(engagements): first-time engagements with readiness and region checks"
```

---

### Task 4: Reactivation — prefill and idempotent create

**Files:**
- Modify: `backend/app/modules/engagements/repository.py`, `schemas.py`, `engagements.py`, `router.py`
- Test: `backend/tests/api/engagements/test_reactivation.py`

**Interfaces:**
- Consumes: `EngagementService.create`, `staffed_project` (Task 3).
- Produces:
  - `EngagementRepository.latest_for_worker(worker_id) -> Engagement | None` (most recent non-cancelled by start date), `get_by_idempotency_key(key)`.
  - Schemas `ReactivationPrefill(prefilled_from_engagement_id, rate, currency, work_mode, location, contract_terms, last_days_to_start: float | None)`, `ReactivationCreate(EngagementCreate + prefilled_from_engagement_id: UUID | None)`.
  - `EngagementService.prefill(actor, worker_id, project_id) -> ReactivationPrefill`; `EngagementService.reactivate(actor, worker_id, data, idempotency_key) -> tuple[Engagement, bool]` (bool = replayed).
  - Routes `GET /api/v1/workers/{worker_id}/reactivation-prefill?project_id=` (permission `ENGAGEMENT_REACTIVATE`, guard `SUMMARY`) and `POST /api/v1/workers/{worker_id}/reactivations` (permission `ENGAGEMENT_REACTIVATE`, guard `SUMMARY`, header `Idempotency-Key`; 201, or 200 on replay).
  - Error codes `idempotency_key_required` (400), `idempotency_key_reused` (409), `invalid_prefill_source` (400), `no_prior_engagement` (404 for prefill, 409 for create).

Prefill needs only **summary** visibility (deviation from spec §7.2, which lists detail): the reactivation that FR-4.3 exists for is a new PM re-engaging someone a different PM worked with, and that PM only has summary visibility until the engagement exists. Prefill returns only contract terms — never feedback or history. Recorded as a deviation in Task 11.

An `Idempotency-Key` is 8–64 characters of `[A-Za-z0-9_-]`. Replaying a key the same PM already used for the same worker returns that engagement with 200; any other reuse is 409.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/engagements/test_reactivation.py`:

```python
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.engagements.enums import EngagementStatus, WorkMode
from app.modules.engagements.models import Engagement, Project
from app.modules.passport.models import Worker
from tests.support import (
    bearer,
    engagement_terms,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

KEY = {"Idempotency-Key": "reactivate-kofi-0001"}


def _prefill(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/reactivation-prefill"


def _reactivate(worker_id: object) -> str:
    return f"/api/v1/workers/{worker_id}/reactivations"


async def _kofi_with_history(session: AsyncSession) -> tuple[Worker, Engagement, Project]:
    """Kofi worked on another PM's project; Ama now staffs a new GH project."""
    worker, _ = await make_ready_worker(session)
    old_project = await make_project(session, name="Old")
    older = await make_engagement(
        session, worker_id=worker.id, project_id=old_project.id, start_date=date(2025, 1, 6)
    )
    latest = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=old_project.id,
        start_date=date(2025, 9, 1),
        rate=Decimal("520.00"),
        work_mode=WorkMode.HYBRID,
        scope="Maintain the pipeline",
    )
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=old_project.id,
        start_date=date(2026, 1, 1),
        status=EngagementStatus.CANCELLED,
    )
    assert older.id != latest.id
    return worker, latest, old_project


async def test_prefill_returns_the_latest_non_cancelled_terms(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, latest, _ = await _kofi_with_history(session)

    response = await client.get(
        _prefill(worker.id), params={"project_id": str(project.id)}, headers=bearer(settings, ama)
    )

    body = response.json()
    assert response.status_code == 200
    assert body["prefilled_from_engagement_id"] == str(latest.id)
    assert (body["rate"], body["work_mode"]) == ("520.00", "hybrid")
    assert body["contract_terms"]["scope"] == "Maintain the pipeline"
    assert "feedback" not in body


async def test_prefill_without_history_is_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])
    worker, _ = await make_ready_worker(session)

    response = await client.get(
        _prefill(worker.id), params={"project_id": str(project.id)}, headers=bearer(settings, ama)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "no_prior_engagement"


async def test_reactivation_creates_one_engagement_even_when_replayed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, latest, _ = await _kofi_with_history(session)
    body = engagement_terms(project.id, prefilled_from_engagement_id=str(latest.id))
    headers = bearer(settings, ama) | KEY

    first = await client.post(_reactivate(worker.id), json=body, headers=headers)
    second = await client.post(_reactivate(worker.id), json=body, headers=headers)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["path"] == "reactivation"
    assert first.json()["prefilled_from_engagement_id"] == str(latest.id)
    new = (
        await session.scalars(select(Engagement).where(Engagement.project_id == project.id))
    ).all()
    assert len(new) == 1


async def test_key_reused_for_another_worker_is_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    kofi, _, old = await _kofi_with_history(session)
    grace, _ = await make_ready_worker(session, email="grace@example.com")
    await make_engagement(session, worker_id=grace.id, project_id=old.id)
    headers = bearer(settings, ama) | KEY
    await client.post(_reactivate(kofi.id), json=engagement_terms(project.id), headers=headers)

    response = await client.post(
        _reactivate(grace.id), json=engagement_terms(project.id), headers=headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_key_reused"


async def test_idempotency_key_is_required_and_well_formed(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, _, _ = await _kofi_with_history(session)
    url = _reactivate(worker.id)
    body = engagement_terms(project.id)

    missing = await client.post(url, json=body, headers=bearer(settings, ama))
    malformed = await client.post(
        url, json=body, headers=bearer(settings, ama) | {"Idempotency-Key": "bad key!"}
    )

    assert missing.json()["code"] == "idempotency_key_required"
    assert malformed.json()["code"] == "idempotency_key_required"


async def test_prefill_source_must_belong_to_the_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    kofi, _, old = await _kofi_with_history(session)
    grace, _ = await make_ready_worker(session, email="grace@example.com")
    graces = await make_engagement(session, worker_id=grace.id, project_id=old.id)

    response = await client.post(
        _reactivate(kofi.id),
        json=engagement_terms(project.id, prefilled_from_engagement_id=str(graces.id)),
        headers=bearer(settings, ama) | KEY,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_prefill_source"


async def test_open_engagement_on_the_same_project_is_a_conflict(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama], name="New")
    worker, _, _ = await _kofi_with_history(session)
    await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.ACTIVE
    )

    response = await client.post(
        _reactivate(worker.id), json=engagement_terms(project.id), headers=bearer(settings, ama) | KEY
    )

    assert response.json()["code"] == "engagement_already_open"


async def test_first_timer_cannot_be_reactivated(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[ama])
    worker, _ = await make_ready_worker(session)

    response = await client.post(
        _reactivate(worker.id), json=engagement_terms(project.id), headers=bearer(settings, ama) | KEY
    )

    assert response.json()["code"] == "no_prior_engagement"
```


- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/engagements/test_reactivation.py -v`
Expected: FAIL — 404/405 for the new routes.

- [ ] **Step 3: Implement**

Append to `EngagementRepository` in `backend/app/modules/engagements/repository.py`:

```python
    async def latest_for_worker(self, worker_id: UUID) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement)
            .where(
                Engagement.worker_id == worker_id,
                Engagement.status != EngagementStatus.CANCELLED,
            )
            .order_by(Engagement.start_date.desc(), Engagement.created_at.desc())
            .limit(1)
        )

    async def get_by_idempotency_key(self, key: str) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(Engagement.idempotency_key == key)
        )
```

Append to `backend/app/modules/engagements/schemas.py`:

```python
class ReactivationPrefill(BaseModel):
    """Contract terms from the most recent engagement (FR-4.4). No history,
    no feedback: prefill needs only summary visibility."""

    prefilled_from_engagement_id: UUID
    rate: Decimal
    currency: str
    work_mode: WorkMode
    location: str | None
    contract_terms: ContractTerms
    last_days_to_start: float | None


class ReactivationCreate(EngagementCreate):
    prefilled_from_engagement_id: UUID | None = None
```

Add to `EngagementService` in `backend/app/modules/engagements/engagements.py` (imports: `re`, `BadRequest`, `ReactivationCreate, ReactivationPrefill, ContractTerms`):

```python
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
```

```python
    async def prefill(
        self, actor: Actor, worker_id: UUID, project_id: UUID
    ) -> ReactivationPrefill:
        await self.staffed_project(actor, project_id)
        latest = await self.engagements.latest_for_worker(worker_id)
        if latest is None:
            raise NotFound("No earlier engagement to reactivate", code="no_prior_engagement")
        days = None
        if latest.billable_start_at is not None:
            days = round((latest.billable_start_at - latest.confirmed_at).total_seconds() / 86400, 2)
        return ReactivationPrefill(
            prefilled_from_engagement_id=latest.id,
            rate=latest.rate,
            currency=latest.currency,
            work_mode=latest.work_mode,
            location=latest.location,
            contract_terms=ContractTerms.model_validate(latest.contract_terms),
            last_days_to_start=days,
        )

    async def reactivate(
        self,
        actor: Actor,
        worker_id: UUID,
        data: ReactivationCreate,
        idempotency_key: str | None,
    ) -> tuple[Engagement, bool]:
        """Returns (engagement, replayed). A replay of the same PM's key for the
        same worker returns the original engagement (spec §8.4)."""
        if idempotency_key is None or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise BadRequest(
                "Send an Idempotency-Key header of 8-64 letters, digits, '-' or '_'",
                code="idempotency_key_required",
            )
        existing = await self.engagements.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.worker_id == worker_id and existing.created_by_id == actor.user_id:
                return existing, True
            raise Conflict(*_CONSTRAINT_CODES["uq_engagements_idempotency_key"])
        if data.prefilled_from_engagement_id is not None:
            source = await self.engagements.get(data.prefilled_from_engagement_id)
            if source is None or source.worker_id != worker_id:
                raise BadRequest(
                    "The prefill source must be one of this worker's engagements",
                    code="invalid_prefill_source",
                )
        terms = EngagementCreate.model_validate(
            data.model_dump(exclude={"prefilled_from_engagement_id"})
        )
        engagement = await self.create(
            actor,
            worker_id,
            terms,
            path=EngagementPath.REACTIVATION,
            idempotency_key=idempotency_key,
            prefilled_from=data.prefilled_from_engagement_id,
        )
        return engagement, False
```

Add to `backend/app/modules/engagements/router.py` (imports: `Header, Query, Response` from fastapi; `ReactivationCreate, ReactivationPrefill`):

```python
Reactivator = Annotated[Actor, Depends(require_permission(Permission.ENGAGEMENT_REACTIVATE))]


@router.get("/workers/{worker_id}/reactivation-prefill")
async def reactivation_prefill(
    worker_id: UUID,
    project_id: Annotated[UUID, Query()],
    actor: Reactivator,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> ReactivationPrefill:
    return await EngagementService(session).prefill(actor, worker_id, project_id)


@router.post(
    "/workers/{worker_id}/reactivations",
    status_code=201,
    responses={200: {"model": EngagementRead, "description": "Replayed Idempotency-Key"}},
)
async def reactivate_worker(
    worker_id: UUID,
    body: ReactivationCreate,
    actor: Reactivator,
    session: SessionDep,
    response: Response,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EngagementRead:
    engagement, replayed = await EngagementService(session).reactivate(
        actor, worker_id, body, idempotency_key
    )
    if replayed:
        response.status_code = 200
    return engagement_read(engagement, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/engagements -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(engagements): reactivation prefill and idempotent reactivation"
```

---

### Task 5: E-sign and payroll adapters, webhook signatures

**Files:**
- Create: `backend/app/modules/integrations/esign.py`, `payroll.py`, `webhooks.py`
- Modify: `backend/app/modules/integrations/service.py`, `backend/app/core/config.py`, `backend/.env.example`, `backend/app/wiring.py`, `backend/app/worker/settings.py`, `backend/tests/conftest.py`, `backend/tests/unit/test_config.py`
- Test: `backend/tests/unit/integrations/test_webhooks.py`, `backend/tests/unit/integrations/test_adapters.py`

**Interfaces:**
- Produces:
  - Settings: `esign_provider: Literal["fake"] = "fake"`, `payroll_provider: Literal["fake"] = "fake"`, `esign_webhook_secret: SecretStr` (required; ≥32 chars and no placeholder outside dev/test).
  - `ContractDocument(engagement_id, signer_name, signer_email, project_name, start_date, end_date, rate, currency, work_mode, scope, access_notes)`; `EsignAdapter` protocol `async send_contract(document) -> str` (envelope id; idempotent per engagement); `FakeEsignAdapter` with `.sent: dict[UUID, ContractDocument]`, envelope id `f"fake-env-{engagement_id}"`.
  - `PayrollActivation(engagement_id, worker_id, start_date, rate, currency)`; `PayrollAdapter` protocol `async signal_active(activation) -> None` (idempotent per engagement); `FakePayrollAdapter` with `.activations: dict[UUID, PayrollActivation]`.
  - `sign_payload(secret, timestamp, body) -> str` (`"sha256=" + hex HMAC-SHA256 of f"{timestamp}." + body`); `verify_signature(secret, *, timestamp_header, signature_header, body, now) -> bool` (±300 s tolerance).
  - `build_esign(settings)`, `build_payroll(settings)` — fakes only in dev/test, else `RuntimeError`.
  - `HandlerDeps` gains `esign: EsignAdapter`, `payroll: PayrollAdapter`; test fixtures `esign`, `payroll`; the `drain` fixture wires them.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/integrations/test_webhooks.py`:

```python
from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.modules.integrations.service import sign_payload, verify_signature

SECRET = "esign-webhook-secret-for-tests-0123456789"
BODY = b'{"envelope_id":"fake-env-1","event":"signed"}'


def _headers(ts: int, body: bytes = BODY, secret: str = SECRET) -> dict[str, str]:
    return {"timestamp_header": str(ts), "signature_header": sign_payload(secret, ts, body)}


def test_valid_signature_verifies() -> None:
    now = utcnow()

    assert verify_signature(SECRET, body=BODY, now=now, **_headers(int(now.timestamp())))


@pytest.mark.parametrize(
    "case",
    ["tampered_body", "wrong_secret", "stale", "future", "missing", "non_numeric"],
)
def test_invalid_signatures_are_rejected(case: str) -> None:
    now = utcnow()
    ts = int(now.timestamp())
    kwargs: dict[str, str | None] = dict(_headers(ts))
    body = BODY
    if case == "tampered_body":
        body = BODY.replace(b"signed", b"declined")
    elif case == "wrong_secret":
        kwargs = dict(_headers(ts, secret="another-secret-0123456789-0123456789"))
    elif case == "stale":
        kwargs = dict(_headers(int((now - timedelta(minutes=6)).timestamp())))
    elif case == "future":
        kwargs = dict(_headers(int((now + timedelta(minutes=6)).timestamp())))
    elif case == "missing":
        kwargs = {"timestamp_header": None, "signature_header": None}
    elif case == "non_numeric":
        kwargs["timestamp_header"] = "yesterday"

    assert not verify_signature(SECRET, body=body, now=now, **kwargs)
```

`backend/tests/unit/integrations/test_adapters.py`:

```python
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.integrations.service import (
    ContractDocument,
    FakeEsignAdapter,
    FakePayrollAdapter,
    PayrollActivation,
    build_esign,
    build_payroll,
)


def _document() -> ContractDocument:
    return ContractDocument(
        engagement_id=uuid4(),
        signer_name="Kofi Mensah",
        signer_email="kofi@example.com",
        project_name="Project Volta",
        start_date=date(2026, 10, 1),
        end_date=None,
        rate=Decimal("450.00"),
        currency="GHS",
        work_mode="remote",
        scope="Build the data pipeline",
        access_notes=None,
    )


async def test_fake_esign_is_idempotent_per_engagement() -> None:
    esign = FakeEsignAdapter()
    document = _document()

    first = await esign.send_contract(document)
    second = await esign.send_contract(document)

    assert first == second == f"fake-env-{document.engagement_id}"
    assert list(esign.sent) == [document.engagement_id]


async def test_fake_payroll_records_one_activation_per_engagement() -> None:
    payroll = FakePayrollAdapter()
    activation = PayrollActivation(
        engagement_id=uuid4(), worker_id=uuid4(), start_date=date(2026, 10, 1),
        rate=Decimal("450.00"), currency="GHS",
    )

    await payroll.signal_active(activation)
    await payroll.signal_active(activation)

    assert list(payroll.activations.values()) == [activation]


def test_fakes_are_built_in_dev_and_test(settings: Settings) -> None:
    assert isinstance(build_esign(settings), FakeEsignAdapter)
    assert isinstance(build_payroll(settings), FakePayrollAdapter)


@pytest.mark.parametrize("builder", [build_esign, build_payroll])
def test_fakes_are_refused_in_production(
    settings: Settings, builder: Callable[[Settings], object]
) -> None:
    with pytest.raises(RuntimeError, match="adapter"):
        builder(settings.model_copy(update={"env": "prod"}))
```

Append to `backend/tests/unit/test_config.py`:

```python
def test_prod_esign_webhook_secret_must_be_strong() -> None:
    with pytest.raises(ValidationError, match="esign_webhook_secret"):
        Settings(**_prod_kwargs(esign_webhook_secret=SecretStr("short")))
```

and add `"esign_webhook_secret": SecretStr("c" * 32),` to the dict in `_prod_kwargs`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/integrations tests/unit/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'sign_payload'` and a `Settings` validation difference.

- [ ] **Step 3: Implement**

In `backend/app/core/config.py`, add `from typing import Literal`, then these `Settings` fields after `data_regions`:

```python
    # E-sign and payroll adapters (spec §5.1 integrations). Only fakes exist
    # until providers are selected — a pre-live gate (spec §10).
    esign_provider: Literal["fake"] = "fake"
    payroll_provider: Literal["fake"] = "fake"
    esign_webhook_secret: SecretStr
```

and in `_require_production_hardening`, after the SCIM check:

```python
        _check_strong_secret(self.esign_webhook_secret, field="esign_webhook_secret")
```

Add `ESIGN_WEBHOOK_SECRET=change-me-to-32-plus-random-bytes-please` to `backend/.env.example`.

In `backend/tests/conftest.py`'s `settings` fixture add `esign_webhook_secret=SecretStr("esign-webhook-secret-for-tests-0123456789"),`.

`backend/app/modules/integrations/esign.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ContractDocument:
    engagement_id: UUID
    signer_name: str
    signer_email: str
    project_name: str
    start_date: date
    end_date: date | None
    rate: Decimal
    currency: str
    work_mode: str
    scope: str
    access_notes: str | None


class EsignAdapter(Protocol):
    async def send_contract(self, document: ContractDocument) -> str:
        """Sends the envelope and returns its id. Must be idempotent per
        engagement_id: a retried handler must not create a second envelope."""
        ...


class FakeEsignAdapter:
    """Dev/test stand-in. Records what it would send; never signs by itself."""

    def __init__(self) -> None:
        self.sent: dict[UUID, ContractDocument] = {}

    async def send_contract(self, document: ContractDocument) -> str:
        self.sent[document.engagement_id] = document
        return f"fake-env-{document.engagement_id}"
```

`backend/app/modules/integrations/payroll.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PayrollActivation:
    engagement_id: UUID
    worker_id: UUID
    start_date: date
    rate: Decimal
    currency: str


class PayrollAdapter(Protocol):
    async def signal_active(self, activation: PayrollActivation) -> None:
        """Tells payments an engagement is billable (FR-8.3). Idempotent per
        engagement_id; payment logic stays in the payments system."""
        ...


class FakePayrollAdapter:
    def __init__(self) -> None:
        self.activations: dict[UUID, PayrollActivation] = {}

    async def signal_active(self, activation: PayrollActivation) -> None:
        self.activations[activation.engagement_id] = activation
```

`backend/app/modules/integrations/webhooks.py`:

```python
import hashlib
import hmac
from datetime import datetime

SIGNATURE_TOLERANCE_SECONDS = 300


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str,
    *,
    timestamp_header: str | None,
    signature_header: str | None,
    body: bytes,
    now: datetime,
) -> bool:
    """HMAC over "<timestamp>.<body>"; the timestamp bounds replay (spec §8.1)."""
    if not timestamp_header or not signature_header:
        return False
    try:
        timestamp = int(timestamp_header)
    except ValueError:
        return False
    if abs(now.timestamp() - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    return hmac.compare_digest(sign_payload(secret, timestamp, body), signature_header)
```

Replace `backend/app/modules/integrations/service.py` with:

```python
"""Public interface of the integrations module."""

from app.core.config import NON_PRODUCTION_ENVS, Settings
from app.core.mail import ConsoleMailer, Mailer
from app.modules.integrations.esign import ContractDocument, EsignAdapter, FakeEsignAdapter
from app.modules.integrations.payroll import (
    FakePayrollAdapter,
    PayrollActivation,
    PayrollAdapter,
)
from app.modules.integrations.smtp import SmtpMailer
from app.modules.integrations.webhooks import sign_payload, verify_signature


def build_mailer(settings: Settings) -> Mailer:
    if settings.smtp_url is not None:
        return SmtpMailer(
            settings.smtp_url.get_secret_value(),
            settings.mail_from,
            require_tls=settings.env not in NON_PRODUCTION_ENVS,
        )
    if settings.env in NON_PRODUCTION_ENVS:
        # ConsoleMailer logs full sign-in links: acceptable only on a
        # developer's own machine or in tests.
        return ConsoleMailer()
    raise RuntimeError("A real mailer must be configured outside dev/test: set SMTP_URL")


def build_esign(settings: Settings) -> EsignAdapter:
    if settings.env not in NON_PRODUCTION_ENVS:
        raise RuntimeError("A real e-signature adapter must be configured outside dev/test")
    return FakeEsignAdapter()


def build_payroll(settings: Settings) -> PayrollAdapter:
    if settings.env not in NON_PRODUCTION_ENVS:
        raise RuntimeError("A real payroll adapter must be configured outside dev/test")
    return FakePayrollAdapter()


__all__ = [
    "ContractDocument",
    "EsignAdapter",
    "FakeEsignAdapter",
    "FakePayrollAdapter",
    "PayrollActivation",
    "PayrollAdapter",
    "SmtpMailer",
    "build_esign",
    "build_mailer",
    "build_payroll",
    "sign_payload",
    "verify_signature",
]
```

(Keep `build_mailer` exactly as it currently is in the file if it differs from the above — only add the new imports, builders and exports.)

In `backend/app/wiring.py`, add to `HandlerDeps`:

```python
    esign: EsignAdapter
    payroll: PayrollAdapter
```

(import both from `app.modules.integrations.service`).

In `backend/app/worker/settings.py`, import `build_esign, build_payroll` and pass `esign=build_esign(settings), payroll=build_payroll(settings)` to `HandlerDeps`.

In `backend/tests/conftest.py`, add fixtures and wire them into `drain`:

```python
@pytest.fixture
def esign() -> FakeEsignAdapter:
    return FakeEsignAdapter()


@pytest.fixture
def payroll() -> FakePayrollAdapter:
    return FakePayrollAdapter()
```

and give `drain` parameters `esign: FakeEsignAdapter, payroll: FakePayrollAdapter`, building `HandlerDeps(settings=..., redis=..., mailer=mailer, esign=esign, payroll=payroll)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add .env.example app tests
git commit -m "feat(integrations): e-sign and payroll adapters with fakes; webhook signatures"
```

---

### Task 6: Contract dispatch, e-sign webhook, activation and payroll

**Files:**
- Create: `backend/app/modules/engagements/contracts.py`, `backend/app/modules/engagements/payroll.py`
- Modify: `backend/app/modules/identity/accounts.py`, `backend/app/modules/identity/service.py`, `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/service.py`, `backend/app/modules/engagements/repository.py`, `schemas.py`, `engagements.py`, `handlers.py`, `router.py`; `backend/app/wiring.py`; `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`; `backend/tests/support.py`
- Test: `backend/tests/api/engagements/test_contracts.py`

**Interfaces:**
- Consumes: adapters and `HandlerDeps` (Task 5); `EngagementService`, `EngagementCreated` (Task 3).
- Produces:
  - Identity: `worker_contact(session, worker_id) -> AccountContact | None`. Passport: `worker_name(session, worker_id) -> str | None`, `mark_worker_active(session, worker_id)`, `mark_worker_dormant(session, worker_id, *, since)`.
  - `EngagementRepository.get_by_envelope_for_update(envelope_id)`, `due_signed(today) -> list[Engagement]`, `active_count(worker_id) -> int`.
  - Events: `ContractDispatchRequested`, `ContractSigned`, `EngagementActivated(worker_id, project_id)`, `EngagementCancelled(worker_id, project_id)` (event types `engagements.contract_dispatch_requested`, `engagements.contract_signed`, `engagements.engagement_activated`, `engagements.engagement_cancelled`); `EsignWebhook(envelope_id, event: Literal["signed", "declined"])`.
  - `contracts.send_contract(session, esign, engagement_id)`, `contracts.activate(session, engagement)`, `contracts.activate_due(session) -> int`, `ContractService(session)` with `handle_webhook(event)` and `request_retry(actor, engagement_id) -> Engagement`; `payroll.signal_payroll(session, payroll, engagement_id)`; `sync_worker_status(session, worker_id)`.
  - `EngagementService.managed(actor, engagement_id) -> Engagement` (PM staffed on its project, else 404 `engagement_not_found`).
  - Handlers (`register(registry, *, esign, payroll)`): `engagements.send_contract` (EngagementCreated), `engagements.resend_contract` (ContractDispatchRequested), `engagements.signal_payroll` and `engagements.sync_worker_status_on_activation` (EngagementActivated), `engagements.sync_worker_status_on_cancellation` (EngagementCancelled).
  - Routes `POST /api/v1/webhooks/esign` (204; headers `X-Bonarda-Timestamp`, `X-Bonarda-Signature`) and `POST /api/v1/engagements/{engagement_id}/contract/retry` (202; permission `ENGAGEMENT_CREATE`).
  - Arq cron `activate_due_engagements` (hourly, minute 0).
  - Error codes `webhook_signature_invalid` (401), `invalid_webhook_payload` (400), `envelope_not_found` (404), `engagement_not_found` (404), `contract_not_retryable` (409).
  - Test helper `esign_webhook(settings, payload) -> tuple[bytes, dict[str, str]]`.

State machine: `pending_signature` → (contract sent) `awaiting_signature` → (signed) `signed` → (start date reached) `active`; `declined` cancels a not-yet-signed engagement. Every transition is guarded by the current status, so replayed or out-of-order webhooks and retried handlers are no-ops. Payroll is signalled once per engagement (`payroll_signaled_at`). Worker status follows engagements: any active engagement → `active`; none → `dormant` (Task 7 adds completion).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/support.py` (imports: `json`; `from app.modules.integrations.service import sign_payload`):

```python
def esign_webhook(settings: Settings, payload: dict[str, object]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    timestamp = int(utcnow().timestamp())
    secret = settings.esign_webhook_secret.get_secret_value()
    return body, {
        "Content-Type": "application/json",
        "X-Bonarda-Timestamp": str(timestamp),
        "X-Bonarda-Signature": sign_payload(secret, timestamp, body),
    }
```

`backend/tests/api/engagements/test_contracts.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.contracts import activate_due
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.identity.models import UserAccount
from app.modules.integrations.service import FakeEsignAdapter, FakePayrollAdapter
from app.modules.passport.enums import WorkerStatus
from app.modules.passport.models import Worker
from tests.support import (
    bearer,
    engagement_terms,
    esign_webhook,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]
WEBHOOK = "/api/v1/webhooks/esign"


async def _engage(
    client: AsyncClient, session: AsyncSession, settings: Settings, **overrides: object
) -> tuple[dict[str, Any], Worker, UserAccount]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session, email="kofi@example.com")
    response = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id, **overrides),
        headers=bearer(settings, pm),
    )
    assert response.status_code == 201
    return response.json(), worker, pm


async def _engagement(session: AsyncSession, engagement_id: object) -> Engagement:
    row = await session.get(Engagement, engagement_id)
    assert row is not None
    await session.refresh(row)
    return row


async def _sign(
    client: AsyncClient, settings: Settings, envelope_id: str, event: str = "signed"
) -> int:
    body, headers = esign_webhook(settings, {"envelope_id": envelope_id, "event": event})
    return (await client.post(WEBHOOK, content=body, headers=headers)).status_code


async def test_contract_is_sent_by_the_worker_process(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    created, worker, _ = await _engage(client, session, settings)

    assert esign.sent == {}
    await drain()

    engagement = await _engagement(session, created["id"])
    document = esign.sent[engagement.id]
    assert (document.signer_email, document.signer_name) == ("kofi@example.com", "Kofi Mensah")
    assert document.project_name == "Project Volta"
    assert engagement.status.value == "awaiting_signature"
    assert engagement.esign_envelope_id == f"fake-env-{engagement.id}"
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "engagement.contract_sent" in actions


async def test_signing_on_or_after_the_start_date_activates_and_signals_payroll(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    payroll: FakePayrollAdapter,
) -> None:
    created, worker, _ = await _engage(client, session, settings)
    await drain()
    engagement = await _engagement(session, created["id"])

    assert await _sign(client, settings, engagement.esign_envelope_id or "") == 204
    await drain()

    engagement = await _engagement(session, created["id"])
    assert engagement.status.value == "active"
    assert engagement.billable_start_at is not None
    assert engagement.payroll_signaled_at is not None
    assert list(payroll.activations) == [engagement.id]
    await session.refresh(worker)
    assert worker.status is WorkerStatus.ACTIVE


async def test_replayed_webhook_changes_nothing(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    payroll: FakePayrollAdapter,
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    envelope = (await _engagement(session, created["id"])).esign_envelope_id or ""
    await _sign(client, settings, envelope)
    await drain()

    again = await _sign(client, settings, envelope)
    declined_late = await _sign(client, settings, envelope, event="declined")
    await drain()

    assert (again, declined_late) == (204, 204)
    engagement = await _engagement(session, created["id"])
    assert engagement.status.value == "active"
    signed = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "engagement.contract_signed")
        )
    ).all()
    assert len(signed) == 1
    assert len(payroll.activations) == 1


async def test_future_start_is_signed_then_activated_once_by_the_hourly_job(
    client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Drain,
) -> None:
    start = (utcnow() + timedelta(days=10)).date().isoformat()
    created, _, _ = await _engage(client, session, settings, start_date=start)
    await drain()
    await _sign(client, settings, (await _engagement(session, created["id"])).esign_envelope_id or "")

    assert (await _engagement(session, created["id"])).status.value == "signed"
    async with sessionmaker() as s, s.begin():
        assert await activate_due(s) == 0
    await session.execute(
        update(Engagement)
        .where(Engagement.id == created["id"])
        .values(start_date=utcnow().date())
    )
    await session.commit()
    async with sessionmaker() as s, s.begin():
        first = await activate_due(s)
    async with sessionmaker() as s, s.begin():
        second = await activate_due(s)

    assert (first, second) == (1, 0)
    assert (await _engagement(session, created["id"])).status.value == "active"


async def test_declined_contract_cancels_the_engagement(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    envelope = (await _engagement(session, created["id"])).esign_envelope_id or ""

    assert await _sign(client, settings, envelope, event="declined") == 204

    assert (await _engagement(session, created["id"])).status.value == "cancelled"


async def test_bad_signatures_and_unknown_envelopes_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    body, headers = esign_webhook(settings, {"envelope_id": "nope", "event": "signed"})

    forged = await client.post(
        WEBHOOK, content=body, headers=headers | {"X-Bonarda-Signature": "sha256=00"}
    )
    unknown = await client.post(WEBHOOK, content=body, headers=headers)
    garbage_body, garbage_headers = esign_webhook(settings, {"event": "signed"})
    garbage = await client.post(WEBHOOK, content=garbage_body, headers=garbage_headers)

    assert (forged.status_code, forged.json()["code"]) == (401, "webhook_signature_invalid")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "envelope_not_found")
    assert (garbage.status_code, garbage.json()["code"]) == (400, "invalid_webhook_payload")


async def test_cancelled_before_dispatch_is_never_sent(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await session.execute(
        update(Engagement)
        .where(Engagement.id == created["id"])
        .values(status=EngagementStatus.CANCELLED)
    )
    await session.commit()

    await drain()

    assert esign.sent == {}


async def test_pm_can_retry_a_waiting_contract(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    created, _, pm = await _engage(client, session, settings)
    await drain()
    esign.sent.clear()

    response = await client.post(
        f"/api/v1/engagements/{created['id']}/contract/retry", headers=bearer(settings, pm)
    )
    await drain()

    assert response.status_code == 202
    assert list(esign.sent) == [(await _engagement(session, created["id"])).id]


async def test_retry_is_refused_once_signed_and_for_unstaffed_pms(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    created, _, pm = await _engage(client, session, settings)
    await drain()
    await _sign(client, settings, (await _engagement(session, created["id"])).esign_envelope_id or "")
    outsider = await make_user(session, role=UserRole.PM)
    url = f"/api/v1/engagements/{created['id']}/contract/retry"

    signed = await client.post(url, headers=bearer(settings, pm))
    hidden = await client.post(url, headers=bearer(settings, outsider))

    assert (signed.status_code, signed.json()["code"]) == (409, "contract_not_retryable")
    assert (hidden.status_code, hidden.json()["code"]) == (404, "engagement_not_found")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/engagements/test_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.engagements.contracts'`.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/identity/accounts.py`:

```python
async def worker_contact(session: AsyncSession, worker_id: UUID) -> AccountContact | None:
    user = await session.scalar(select(UserAccount).where(UserAccount.worker_id == worker_id))
    if user is None:
        return None
    return AccountContact(email=user.email, locale=user.locale)
```

Export `worker_contact` from `identity/service.py`.

Append to `backend/app/modules/passport/queries.py` (imports: `date`, `emit_event`, `WorkerUpdated`):

```python
async def worker_name(session: AsyncSession, worker_id: UUID) -> str | None:
    worker = await WorkerRepository(session).get(worker_id)
    return worker.full_name if worker is not None else None


async def mark_worker_active(session: AsyncSession, worker_id: UUID) -> None:
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status is not WorkerStatus.DORMANT:
        return
    worker.status = WorkerStatus.ACTIVE
    worker.dormant_since = None
    await emit_event(session, WorkerUpdated(aggregate_id=worker_id, fields=["status"]))


async def mark_worker_dormant(session: AsyncSession, worker_id: UUID, *, since: date) -> None:
    """FR-9.7: not engaged is dormant, not deleted."""
    worker = await WorkerRepository(session).get(worker_id)
    if worker is None or worker.status is not WorkerStatus.ACTIVE:
        return
    worker.status = WorkerStatus.DORMANT
    worker.dormant_since = since
    await emit_event(session, WorkerUpdated(aggregate_id=worker_id, fields=["status"]))
```

Export all three from `passport/service.py`.

Append to `EngagementRepository` (import `func` from sqlalchemy, `date`):

```python
    async def get_by_envelope_for_update(self, envelope_id: str) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement)
            .where(Engagement.esign_envelope_id == envelope_id)
            .with_for_update()
        )

    async def due_signed(self, today: date) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(Engagement.status == EngagementStatus.SIGNED, Engagement.start_date <= today)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(stmt)).all())

    async def active_count(self, worker_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Engagement)
            .where(
                Engagement.worker_id == worker_id,
                Engagement.status == EngagementStatus.ACTIVE,
            )
        )
        return int(count or 0)
```

Append to `backend/app/modules/engagements/schemas.py` (import `Literal`):

```python
class EsignWebhook(BaseModel):
    envelope_id: str = Field(min_length=1, max_length=120)
    event: Literal["signed", "declined"]


class ContractDispatchRequested(DomainEvent):
    event_type: ClassVar[str] = "engagements.contract_dispatch_requested"


class ContractSigned(DomainEvent):
    event_type: ClassVar[str] = "engagements.contract_signed"


class EngagementActivated(DomainEvent):
    event_type: ClassVar[str] = "engagements.engagement_activated"
    worker_id: UUID
    project_id: UUID


class EngagementCancelled(DomainEvent):
    event_type: ClassVar[str] = "engagements.engagement_cancelled"
    worker_id: UUID
    project_id: UUID
```

Add to `EngagementService` in `engagements.py`:

```python
    async def managed(self, actor: Actor, engagement_id: UUID) -> Engagement:
        """An engagement the actor may act on: a PM staffed on its project."""
        engagement = await self.engagements.get_for_update(engagement_id)
        if engagement is None or not await self.projects.is_staffed(
            engagement.project_id, actor.user_id
        ):
            raise NotFound("Engagement not found", code="engagement_not_found")
        return engagement
```

`backend/app/modules/engagements/contracts.py`:

```python
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.engagements.engagements import EngagementService
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.repository import EngagementRepository, ProjectRepository
from app.modules.engagements.schemas import (
    ContractDispatchRequested,
    ContractSigned,
    EngagementActivated,
    EngagementCancelled,
    EsignWebhook,
)
from app.modules.identity.service import worker_contact
from app.modules.integrations.service import ContractDocument, EsignAdapter
from app.modules.passport.service import mark_worker_active, mark_worker_dormant, worker_name

log = structlog.get_logger(__name__)
_SENDABLE = (EngagementStatus.PENDING_SIGNATURE, EngagementStatus.AWAITING_SIGNATURE)


async def send_contract(session: AsyncSession, esign: EsignAdapter, engagement_id: UUID) -> None:
    """Outbox handler: sends (or re-sends) the contract. The adapter is
    idempotent per engagement, so a retried handler never makes a second envelope."""
    engagement = await EngagementRepository(session).get_for_update(engagement_id)
    if engagement is None or engagement.status not in _SENDABLE:
        log.info("engagements.contract_not_sent", engagement_id=str(engagement_id))
        return
    project = await ProjectRepository(session).get(engagement.project_id)
    contact = await worker_contact(session, engagement.worker_id)
    name = await worker_name(session, engagement.worker_id)
    if project is None or contact is None or name is None:
        raise RuntimeError(f"engagement {engagement_id} is missing its project or worker")
    envelope_id = await esign.send_contract(
        ContractDocument(
            engagement_id=engagement.id,
            signer_name=name,
            signer_email=contact.email,
            project_name=project.name,
            start_date=engagement.start_date,
            end_date=engagement.end_date,
            rate=engagement.rate,
            currency=engagement.currency,
            work_mode=engagement.work_mode.value,
            scope=engagement.contract_terms["scope"],
            access_notes=engagement.contract_terms.get("access_notes"),
        )
    )
    engagement.esign_envelope_id = envelope_id
    engagement.status = EngagementStatus.AWAITING_SIGNATURE
    engagement.contract_sent_at = utcnow()
    engagement.stuck_flagged_at = None
    await write_audit(
        session,
        actor=None,
        action="engagement.contract_sent",
        target_type="engagement",
        target_id=engagement.id,
        after={"envelope_id": envelope_id},
    )


async def activate(session: AsyncSession, engagement: Engagement) -> None:
    """Billable start (spec §2.2 #9): contract signed and start date reached."""
    engagement.status = EngagementStatus.ACTIVE
    engagement.billable_start_at = utcnow()
    await write_audit(
        session,
        actor=None,
        action="engagement.activated",
        target_type="engagement",
        target_id=engagement.id,
        after={"billable_start_at": engagement.billable_start_at.isoformat()},
    )
    await emit_event(
        session,
        EngagementActivated(
            aggregate_id=engagement.id,
            worker_id=engagement.worker_id,
            project_id=engagement.project_id,
        ),
    )


async def activate_due(session: AsyncSession) -> int:
    """Hourly: signed engagements whose start date has arrived."""
    due = await EngagementRepository(session).due_signed(utcnow().date())
    for engagement in due:
        await activate(session, engagement)
    return len(due)


async def sync_worker_status(session: AsyncSession, worker_id: UUID) -> None:
    if await EngagementRepository(session).active_count(worker_id) > 0:
        await mark_worker_active(session, worker_id)
    else:
        await mark_worker_dormant(session, worker_id, since=utcnow().date())


class ContractService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engagements = EngagementRepository(session)

    async def handle_webhook(self, event: EsignWebhook) -> None:
        engagement = await self.engagements.get_by_envelope_for_update(event.envelope_id)
        if engagement is None:
            raise NotFound("Unknown envelope", code="envelope_not_found")
        if event.event == "signed":
            await self._signed(engagement)
        else:
            await self._declined(engagement)

    async def _signed(self, engagement: Engagement) -> None:
        if engagement.status is not EngagementStatus.AWAITING_SIGNATURE:
            return  # replayed or out-of-order: nothing to do
        engagement.status = EngagementStatus.SIGNED
        engagement.signed_at = utcnow()
        await write_audit(
            self.session,
            actor=None,
            action="engagement.contract_signed",
            target_type="engagement",
            target_id=engagement.id,
        )
        await emit_event(self.session, ContractSigned(aggregate_id=engagement.id))
        if engagement.start_date <= utcnow().date():
            await activate(self.session, engagement)

    async def _declined(self, engagement: Engagement) -> None:
        if engagement.status not in _SENDABLE:
            return
        engagement.status = EngagementStatus.CANCELLED
        await write_audit(
            self.session,
            actor=None,
            action="engagement.contract_declined",
            target_type="engagement",
            target_id=engagement.id,
        )
        await emit_event(
            self.session,
            EngagementCancelled(
                aggregate_id=engagement.id,
                worker_id=engagement.worker_id,
                project_id=engagement.project_id,
            ),
        )

    async def request_retry(self, actor: Actor, engagement_id: UUID) -> Engagement:
        engagement = await EngagementService(self.session).managed(actor, engagement_id)
        if engagement.status not in _SENDABLE:
            raise Conflict(
                "Only an unsigned contract can be re-sent", code="contract_not_retryable"
            )
        engagement.stuck_flagged_at = None
        await write_audit(
            self.session,
            actor=actor,
            action="engagement.contract_retry_requested",
            target_type="engagement",
            target_id=engagement.id,
        )
        await emit_event(self.session, ContractDispatchRequested(aggregate_id=engagement.id))
        return engagement
```

`backend/app/modules/engagements/payroll.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.repository import EngagementRepository
from app.modules.integrations.service import PayrollActivation, PayrollAdapter


async def signal_payroll(session: AsyncSession, payroll: PayrollAdapter, engagement_id: UUID) -> None:
    """Outbox handler (FR-8.3): once per engagement."""
    engagement = await EngagementRepository(session).get_for_update(engagement_id)
    if (
        engagement is None
        or engagement.status is not EngagementStatus.ACTIVE
        or engagement.payroll_signaled_at is not None
    ):
        return
    await payroll.signal_active(
        PayrollActivation(
            engagement_id=engagement.id,
            worker_id=engagement.worker_id,
            start_date=engagement.start_date,
            rate=engagement.rate,
            currency=engagement.currency,
        )
    )
    engagement.payroll_signaled_at = utcnow()
    await write_audit(
        session,
        actor=None,
        action="engagement.payroll_signaled",
        target_type="engagement",
        target_id=engagement.id,
    )
```

Replace `backend/app/modules/engagements/handlers.py` with:

```python
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.contracts import send_contract, sync_worker_status
from app.modules.engagements.payroll import signal_payroll
from app.modules.engagements.projects import end_staffing_for
from app.modules.engagements.schemas import (
    ContractDispatchRequested,
    EngagementActivated,
    EngagementCancelled,
    EngagementCreated,
)
from app.modules.identity.schemas import AccessRevoked
from app.modules.integrations.service import EsignAdapter, PayrollAdapter


def register(
    registry: HandlerRegistry, *, esign: EsignAdapter, payroll: PayrollAdapter
) -> None:
    async def end_staffing(session: AsyncSession, payload: dict[str, Any]) -> None:
        await end_staffing_for(
            session, UUID(payload["aggregate_id"]), reason=payload.get("reason", "access_revoked")
        )

    async def send(session: AsyncSession, payload: dict[str, Any]) -> None:
        await send_contract(session, esign, UUID(payload["aggregate_id"]))

    async def pay(session: AsyncSession, payload: dict[str, Any]) -> None:
        await signal_payroll(session, payroll, UUID(payload["aggregate_id"]))

    async def sync(session: AsyncSession, payload: dict[str, Any]) -> None:
        await sync_worker_status(session, UUID(payload["worker_id"]))

    registry.register(AccessRevoked, "engagements.end_staffing_on_revocation", end_staffing)
    registry.register(EngagementCreated, "engagements.send_contract", send)
    registry.register(ContractDispatchRequested, "engagements.resend_contract", send)
    registry.register(EngagementActivated, "engagements.signal_payroll", pay)
    registry.register(EngagementActivated, "engagements.sync_worker_status_on_activation", sync)
    registry.register(EngagementCancelled, "engagements.sync_worker_status_on_cancellation", sync)
```

In `backend/app/wiring.py`, call `engagements_handlers.register(registry, esign=deps.esign, payroll=deps.payroll)`.

Add to `backend/app/modules/engagements/router.py` (imports: `Request`, `Header` from fastapi; `ValidationError` from pydantic; `BadRequest, Unauthorized` from core.errors; `utcnow`; `verify_signature` from integrations.service; `ContractService` from contracts; `EsignWebhook`):

```python
@router.post("/webhooks/esign", status_code=204)
async def esign_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_bonarda_timestamp: Annotated[str | None, Header()] = None,
    x_bonarda_signature: Annotated[str | None, Header()] = None,
) -> None:
    body = await request.body()
    if not verify_signature(
        settings.esign_webhook_secret.get_secret_value(),
        timestamp_header=x_bonarda_timestamp,
        signature_header=x_bonarda_signature,
        body=body,
        now=utcnow(),
    ):
        raise Unauthorized("Invalid webhook signature", code="webhook_signature_invalid")
    try:
        event = EsignWebhook.model_validate_json(body)
    except ValidationError as exc:
        raise BadRequest("Malformed webhook payload", code="invalid_webhook_payload") from exc
    await ContractService(session).handle_webhook(event)


@router.post("/engagements/{engagement_id}/contract/retry", status_code=202)
async def retry_contract(
    engagement_id: UUID, actor: EngagementCreator, session: SessionDep
) -> EngagementRead:
    engagement = await ContractService(session).request_retry(actor, engagement_id)
    return engagement_read(engagement, None)
```

Append to `backend/app/worker/jobs.py` (import `activate_due` from `app.modules.engagements.contracts`):

```python
async def activate_due_engagements(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await activate_due(session)
```

In `backend/app/worker/settings.py`, import it and add `cron(activate_due_engagements, minute={0})` to `cron_jobs`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/engagements -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(engagements): contract dispatch, signed e-sign webhook, activation and payroll"
```

---

### Task 7: Completion and structured feedback

**Files:**
- Create: `backend/app/modules/engagements/feedback.py`
- Modify: `backend/app/modules/passport/queries.py`, `backend/app/modules/passport/service.py`, `backend/app/modules/engagements/schemas.py`, `engagements.py`, `handlers.py`, `router.py`
- Test: `backend/tests/api/engagements/test_completion_and_feedback.py`

**Interfaces:**
- Consumes: `EngagementService.managed` (Task 6); `sync_worker_status` (Task 6).
- Produces:
  - Passport: `claimed_skill_ids(session, worker_id) -> set[UUID]` exported from `passport.service`.
  - Schemas `CompletionRequest(end_date: date | None)`, `StructuredAnswers` (the three FR-2.3 booleans, extra forbidden), `FeedbackCreate(structured_answers, free_text ≤2000, skill_ids_demonstrated ≤20, de-duplicated)`; events `EngagementCompleted(worker_id, project_id)` (`engagements.engagement_completed`) and `FeedbackSubmitted(worker_id, reviewer_id, skill_ids_demonstrated)` (`engagements.feedback_submitted`, aggregate = engagement id).
  - `EngagementService.complete(actor, engagement_id, data) -> Engagement`; `FeedbackService(session).submit(actor, engagement_id, data) -> tuple[Engagement, Feedback]`.
  - Handler `engagements.sync_worker_status_on_completion` (EngagementCompleted).
  - Routes `POST /api/v1/engagements/{engagement_id}/complete` (200; `ENGAGEMENT_CREATE`) and `POST /api/v1/engagements/{engagement_id}/feedback` (201; `FEEDBACK_SUBMIT`).
  - Error codes `engagement_not_active` (409), `invalid_end_date` (400), `engagement_not_completed` (409), `feedback_exists` (409), `skill_not_claimed` (400).

Feedback is visible to the worker in full (FR-2.4, through `GET /workers/{id}/engagements`). The audit row records the structured answers only — never the free text.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/engagements/test_completion_and_feedback.py`:

```python
import json
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import WorkerStatus
from app.modules.passport.models import Skill, Worker
from tests.support import bearer, make_engagement, make_project, make_ready_worker, make_user

Drain = Callable[[], Awaitable[None]]
ANSWERS = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": False,
    "would_reengage": True,
}


async def _active(session: AsyncSession) -> tuple[UserAccount, Worker, Engagement]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, account = await make_ready_worker(session)
    worker.status = WorkerStatus.ACTIVE
    await session.commit()
    engagement = await make_engagement(
        session, worker_id=worker.id, project_id=project.id, status=EngagementStatus.ACTIVE
    )
    return pm, worker, engagement


async def test_completing_the_last_active_engagement_makes_the_worker_dormant(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _active(session)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, pm)
    )
    await drain()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["end_date"] == utcnow().date().isoformat()
    await session.refresh(worker)
    assert (worker.status, worker.dormant_since) == (WorkerStatus.DORMANT, utcnow().date())


async def test_worker_with_another_active_engagement_stays_active(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    pm, worker, engagement = await _active(session)
    await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, name="Other")).id,
        status=EngagementStatus.ACTIVE,
    )

    await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, pm)
    )
    await drain()

    await session.refresh(worker)
    assert worker.status is WorkerStatus.ACTIVE


async def test_only_active_engagements_complete(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, worker, _ = await _active(session)
    signed = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="Signed")).id,
        status=EngagementStatus.SIGNED,
    )

    response = await client.post(
        f"/api/v1/engagements/{signed.id}/complete", json={}, headers=bearer(settings, pm)
    )

    assert response.json()["code"] == "engagement_not_active"


async def test_feedback_is_recorded_published_and_visible_to_the_worker(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, worker, engagement = await _active(session)
    skill = await session.scalar(select(Skill))
    assert skill is not None
    await client.post(
        f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=bearer(settings, pm)
    )

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={
            "structured_answers": ANSWERS,
            "free_text": "Reliable; flagged risks early.",
            "skill_ids_demonstrated": [str(skill.id)] * 2,
        },
        headers=bearer(settings, pm),
    )

    assert response.status_code == 201
    feedback = response.json()["feedback"]
    assert feedback["skill_ids_demonstrated"] == [str(skill.id)]
    event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "engagements.feedback_submitted")
        )
    ).one()
    assert event.payload["reviewer_id"] == str(pm.id)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "feedback.submitted"))
    ).one()
    assert "Reliable" not in json.dumps([audit.before, audit.after])
    history = await client.get(
        f"/api/v1/workers/{worker.id}/engagements",
        headers=bearer(settings, await _account_of(session, worker)),
    )
    assert history.json()[0]["feedback"]["free_text"] == "Reliable; flagged risks early."


async def _account_of(session: AsyncSession, worker: Worker) -> UserAccount:
    return (
        await session.scalars(select(UserAccount).where(UserAccount.worker_id == worker.id))
    ).one()


async def test_feedback_rules(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm, _, engagement = await _active(session)
    url = f"/api/v1/engagements/{engagement.id}/feedback"
    headers = bearer(settings, pm)

    too_early = await client.post(url, json={"structured_answers": ANSWERS}, headers=headers)
    await client.post(f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=headers)
    unclaimed = await client.post(
        url,
        json={"structured_answers": ANSWERS, "skill_ids_demonstrated": [str(uuid4())]},
        headers=headers,
    )
    first = await client.post(url, json={"structured_answers": ANSWERS}, headers=headers)
    duplicate = await client.post(url, json={"structured_answers": ANSWERS}, headers=headers)

    assert too_early.json()["code"] == "engagement_not_completed"
    assert unclaimed.json()["code"] == "skill_not_claimed"
    assert first.status_code == 201
    assert duplicate.json()["code"] == "feedback_exists"


@pytest.mark.parametrize(
    "answers",
    [
        {"delivered_on_agreed_dates": True, "would_reengage": True},
        ANSWERS | {"mood": True},
    ],
)
async def test_structured_answers_must_be_exactly_the_three_questions(
    client: AsyncClient, session: AsyncSession, settings: Settings, answers: dict[str, bool]
) -> None:
    pm, _, engagement = await _active(session)
    headers = bearer(settings, pm)
    await client.post(f"/api/v1/engagements/{engagement.id}/complete", json={}, headers=headers)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": answers},
        headers=headers,
    )

    assert response.status_code == 422


async def test_people_ops_cannot_submit_feedback(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, _, engagement = await _active(session)
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": ANSWERS},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 403
```


- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/engagements/test_completion_and_feedback.py -v`
Expected: FAIL — 404/405 for `/complete` and `/feedback`.

- [ ] **Step 3: Implement**

Append to `backend/app/modules/passport/queries.py`:

```python
async def claimed_skill_ids(session: AsyncSession, worker_id: UUID) -> set[UUID]:
    return {
        claim.skill_id for claim, _ in await SkillClaimRepository(session).list_for_worker(worker_id)
    }
```

Export it from `passport/service.py`.

Append to `backend/app/modules/engagements/schemas.py`:

```python
class CompletionRequest(BaseModel):
    end_date: date | None = None


class StructuredAnswers(BaseModel):
    """FR-2.3 — behaviour-specific questions; all required, nothing else."""

    model_config = ConfigDict(extra="forbid")

    delivered_on_agreed_dates: bool
    handled_scope_changes_without_escalation: bool
    would_reengage: bool


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_answers: StructuredAnswers
    free_text: str | None = Field(default=None, max_length=2000)
    skill_ids_demonstrated: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("skill_ids_demonstrated")
    @classmethod
    def _dedupe(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class EngagementCompleted(DomainEvent):
    event_type: ClassVar[str] = "engagements.engagement_completed"
    worker_id: UUID
    project_id: UUID


class FeedbackSubmitted(DomainEvent):
    """aggregate_id is the engagement; Plan 3's standing handlers consume this."""

    event_type: ClassVar[str] = "engagements.feedback_submitted"
    worker_id: UUID
    reviewer_id: UUID | None
    skill_ids_demonstrated: list[UUID]
```

Add to `EngagementService` (imports: `BadRequest`, `CompletionRequest`, `EngagementCompleted`):

```python
    async def complete(
        self, actor: Actor, engagement_id: UUID, data: CompletionRequest
    ) -> Engagement:
        engagement = await self.managed(actor, engagement_id)
        if engagement.status is not EngagementStatus.ACTIVE:
            raise Conflict("Only an active engagement can be completed", code="engagement_not_active")
        end_date = data.end_date or engagement.end_date or utcnow().date()
        if end_date < engagement.start_date:
            raise BadRequest("end_date is before the start date", code="invalid_end_date")
        engagement.end_date = end_date
        engagement.status = EngagementStatus.COMPLETED
        engagement.completed_at = utcnow()
        await write_audit(
            self.session,
            actor=actor,
            action="engagement.completed",
            target_type="engagement",
            target_id=engagement.id,
            after={"end_date": end_date.isoformat()},
        )
        await emit_event(
            self.session,
            EngagementCompleted(
                aggregate_id=engagement.id,
                worker_id=engagement.worker_id,
                project_id=engagement.project_id,
            ),
        )
        return engagement
```

`backend/app/modules/engagements/feedback.py`:

```python
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict
from app.core.outbox.writer import emit_event
from app.modules.engagements.engagements import EngagementService
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement, Feedback
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import FeedbackCreate, FeedbackSubmitted
from app.modules.passport.service import claimed_skill_ids

_EXISTS = ("Feedback was already submitted for this engagement", "feedback_exists")


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engagements = EngagementRepository(session)

    async def submit(
        self, actor: Actor, engagement_id: UUID, data: FeedbackCreate
    ) -> tuple[Engagement, Feedback]:
        engagement = await EngagementService(self.session).managed(actor, engagement_id)
        if engagement.status is not EngagementStatus.COMPLETED:
            raise Conflict(
                "Feedback opens when the engagement is completed", code="engagement_not_completed"
            )
        if engagement.id in await self.engagements.feedback_for([engagement.id]):
            raise Conflict(*_EXISTS)
        claimed = await claimed_skill_ids(self.session, engagement.worker_id)
        if set(data.skill_ids_demonstrated) - claimed:
            raise BadRequest(
                "Demonstrated skills must be skills the worker lists", code="skill_not_claimed"
            )
        answers = data.structured_answers.model_dump()
        try:
            async with self.session.begin_nested():
                feedback = self.engagements.add_feedback(
                    Feedback(
                        engagement_id=engagement.id,
                        reviewer_id=actor.user_id,
                        structured_answers=answers,
                        free_text=data.free_text,
                        skill_ids_demonstrated=data.skill_ids_demonstrated,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_feedback_engagement_id":
                raise
            raise Conflict(*_EXISTS) from exc
        # Structured answers only: free text is personal data (spec §6.3).
        await write_audit(
            self.session,
            actor=actor,
            action="feedback.submitted",
            target_type="engagement",
            target_id=engagement.id,
            after={"structured_answers": answers},
        )
        await emit_event(
            self.session,
            FeedbackSubmitted(
                aggregate_id=engagement.id,
                worker_id=engagement.worker_id,
                reviewer_id=actor.user_id,
                skill_ids_demonstrated=data.skill_ids_demonstrated,
            ),
        )
        return engagement, feedback
```

In `backend/app/modules/engagements/handlers.py`, import `EngagementCompleted` and add:

```python
    registry.register(EngagementCompleted, "engagements.sync_worker_status_on_completion", sync)
```

Add to `backend/app/modules/engagements/router.py` (imports: `CompletionRequest, FeedbackCreate`, `FeedbackService`):

```python
FeedbackReviewer = Annotated[Actor, Depends(require_permission(Permission.FEEDBACK_SUBMIT))]


@router.post("/engagements/{engagement_id}/complete")
async def complete_engagement(
    engagement_id: UUID, body: CompletionRequest, actor: EngagementCreator, session: SessionDep
) -> EngagementRead:
    engagement = await EngagementService(session).complete(actor, engagement_id, body)
    return engagement_read(engagement, None)


@router.post("/engagements/{engagement_id}/feedback", status_code=201)
async def submit_feedback(
    engagement_id: UUID, body: FeedbackCreate, actor: FeedbackReviewer, session: SessionDep
) -> EngagementRead:
    engagement, feedback = await FeedbackService(session).submit(actor, engagement_id, body)
    return engagement_read(engagement, feedback)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/engagements -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(engagements): completion and structured feedback"
```

---

### Task 8: Stuck-contract detector

**Files:**
- Create: `backend/app/modules/engagements/stuck.py`
- Modify: `backend/app/core/config.py`, `backend/app/modules/engagements/repository.py`, `backend/app/worker/jobs.py`, `backend/app/worker/settings.py`
- Test: `backend/tests/integration/test_stuck_engagements.py`

**Interfaces:**
- Produces: `Settings.stuck_pending_minutes: int = 30`, `Settings.stuck_awaiting_hours: int = 72`; `EngagementRepository.stuck_candidates(pending_before, awaiting_before) -> list[Engagement]`; `stuck.flag_stuck(session, settings) -> int`; Arq cron `flag_stuck_engagements` every 15 minutes.

A contract is stuck when it was confirmed more than 30 minutes ago and still not sent (`pending_signature`), or sent more than 72 hours ago and still unsigned (`awaiting_signature`). Each stuck engagement is flagged once (`stuck_flagged_at`, shown as `stuck: true`), audited and logged at warning level; a retry or a fresh send clears the flag (Task 6).

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_stuck_engagements.py`:

```python
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.stuck import flag_stuck
from tests.support import make_engagement, make_project, make_ready_worker, make_user


async def _run(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    async with sessionmaker() as s, s.begin():
        return await flag_stuck(s, settings)


async def test_old_unsent_and_long_unsigned_contracts_are_flagged_once(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    now = utcnow()
    unsent = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="A")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
    )
    unsigned = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="B")).id,
        status=EngagementStatus.AWAITING_SIGNATURE,
    )
    fresh = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="C")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
    )
    await session.execute(
        update(Engagement)
        .where(Engagement.id == unsent.id)
        .values(confirmed_at=now - timedelta(minutes=31))
    )
    await session.execute(
        update(Engagement)
        .where(Engagement.id == unsigned.id)
        .values(contract_sent_at=now - timedelta(hours=73))
    )
    await session.commit()

    first = await _run(sessionmaker, settings)
    second = await _run(sessionmaker, settings)

    assert (first, second) == (2, 0)
    for engagement in (unsent, unsigned, fresh):
        await session.refresh(engagement)
    assert unsent.stuck_flagged_at is not None
    assert unsigned.stuck_flagged_at is not None
    assert fresh.stuck_flagged_at is None
    flagged = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "engagement.flagged_stuck"))
    ).all()
    assert {row.target_id for row in flagged} == {unsent.id, unsigned.id}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_stuck_engagements.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.engagements.stuck'`.

- [ ] **Step 3: Implement**

In `backend/app/core/config.py`, add after `esign_webhook_secret`:

```python
    # Stuck-contract detector (spec §7.7).
    stuck_pending_minutes: int = 30
    stuck_awaiting_hours: int = 72
```

Append to `EngagementRepository` (import `and_, or_` and `datetime`):

```python
    async def stuck_candidates(
        self, *, pending_before: datetime, awaiting_before: datetime
    ) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(
                Engagement.stuck_flagged_at.is_(None),
                or_(
                    and_(
                        Engagement.status == EngagementStatus.PENDING_SIGNATURE,
                        Engagement.confirmed_at < pending_before,
                    ),
                    and_(
                        Engagement.status == EngagementStatus.AWAITING_SIGNATURE,
                        Engagement.contract_sent_at < awaiting_before,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(stmt)).all())
```

`backend/app/modules/engagements/stuck.py`:

```python
from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.time import utcnow
from app.modules.engagements.repository import EngagementRepository

log = structlog.get_logger(__name__)


async def flag_stuck(session: AsyncSession, settings: Settings) -> int:
    """Every 15 minutes: make contracts that stalled visible to the PM
    (`stuck: true`, retry action) and to engineering (warning log)."""
    now = utcnow()
    stuck = await EngagementRepository(session).stuck_candidates(
        pending_before=now - timedelta(minutes=settings.stuck_pending_minutes),
        awaiting_before=now - timedelta(hours=settings.stuck_awaiting_hours),
    )
    for engagement in stuck:
        engagement.stuck_flagged_at = now
        await write_audit(
            session,
            actor=None,
            action="engagement.flagged_stuck",
            target_type="engagement",
            target_id=engagement.id,
            after={"status": engagement.status.value},
        )
        log.warning(
            "engagements.stuck",
            engagement_id=str(engagement.id),
            status=engagement.status.value,
        )
    return len(stuck)
```

Append to `backend/app/worker/jobs.py` (imports `flag_stuck`, `get_settings` from `app.core.config`):

```python
async def flag_stuck_engagements(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await flag_stuck(session, get_settings())
```

In `backend/app/worker/settings.py`, add `cron(flag_stuck_engagements, minute=set(range(0, 60, 15)))` to `cron_jobs`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_stuck_engagements.py tests/api/engagements -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "feat(engagements): stuck-contract detector"
```

---

### Task 9: Passport carry-forward fixes

**Files:**
- Modify: `backend/app/core/errors.py`, `backend/app/modules/passport/schemas.py`, `profile.py`, `skills.py`, `invitations.py`, `router.py`; `backend/app/modules/identity/accounts.py`
- Test: `backend/tests/api/passport/test_worker_profile.py`, `test_skills.py`, `test_invitations.py`

**Interfaces:**
- Produces: `UnprocessableEntity` (422) in `app.core.errors`; error codes `availability_date_required`, `availability_status_mismatch` (422), `invitation_resend_limited` (429); `INVITATION_RESENDS_PER_HOUR = 3`; `find_worker_account` returns `None` for revoked accounts; the invitation route documents 200.

Carry-forward items closed here (roadmap rows for 2B):
- `WorkerUpdate` availability is validated against the **merged** state, so a worker already at `available_from` can send only a new date.
- Concurrent duplicate skill slug or claim returns 409, not 500.
- Invitation resend: the 200 response is in OpenAPI; a re-invite updates the invited worker's name, type and region (audited before/after); at most 3 resends per worker per hour; a revoked account is not "still invited" (falls through to 409 `email_in_use`).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/api/passport/test_worker_profile.py`:
- In `test_invalid_profile_updates_are_rejected`, remove the two cases `{"availability_status": "available_from"}` and `{"available_from": "2026-11-01"}` from the parametrization (they are now service-level and tested below with their codes).
- Add:

```python
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"availability_status": "available_from"}, "availability_date_required"),
        ({"available_from": "2026-11-01"}, "availability_status_mismatch"),
    ],
)
async def test_inconsistent_availability_is_rejected_with_a_code(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    body: dict[str, object],
    code: str,
) -> None:
    _, account = await make_worker(session)

    response = await client.patch(
        "/api/v1/workers/me", json=body, headers=bearer(settings, account)
    )

    assert response.status_code == 422
    assert response.json()["code"] == code


async def test_worker_already_available_from_can_move_the_date(
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
        "/api/v1/workers/me", json={"available_from": "2026-12-01"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["available_from"] == "2026-12-01"
```

In `backend/tests/api/passport/test_skills.py`, add (imports: `pytest`, `SkillClaimRepository, SkillRepository` from `app.modules.passport.repository`):

```python
async def test_concurrent_duplicate_slug_is_a_conflict_not_a_crash(
    client: AsyncClient, session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    await _skill(session, "data-analysis", "Data analysis")

    async def not_found(self: SkillRepository, slug: str) -> None:
        return None  # simulate the race: the pre-check misses the other insert

    monkeypatch.setattr(SkillRepository, "get_by_slug", not_found)

    response = await client.post(
        "/api/v1/skills",
        json={"slug": "data-analysis", "name_i18n": {"en": "Data analysis"}},
        headers=bearer(settings, ops),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "skill_slug_taken"


async def test_concurrent_duplicate_claim_is_a_conflict_not_a_crash(
    client: AsyncClient, session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, account = await make_worker(session)
    skill = await _skill(session, "data-analysis", "Data analysis")
    session.add(SkillClaim(worker_id=worker.id, skill_id=skill.id))
    await session.commit()

    async def not_found(self: SkillClaimRepository, worker_id: object, skill_id: object) -> None:
        return None

    monkeypatch.setattr(SkillClaimRepository, "get", not_found)

    response = await client.post(
        "/api/v1/workers/me/skills",
        json={"skill_id": str(skill.id)},
        headers=bearer(settings, account),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "skill_already_claimed"
```

In `backend/tests/api/passport/test_invitations.py`, add (imports: `AccountStatus` from `app.core.enums`, `UserAccount`):

```python
async def test_resend_updates_the_invited_workers_details(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    mailer: RecordingMailer,
    drain: Drain,
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, pm)
    await client.post(URL, json=BODY, headers=headers)

    response = await client.post(
        URL, json=BODY | {"full_name": "Grace A. Owusu", "data_region": "EU"}, headers=headers
    )

    assert response.status_code == 200
    worker = (await session.scalars(select(Worker))).one()
    await session.refresh(worker)
    assert (worker.full_name, worker.data_region) == ("Grace A. Owusu", "EU")
    resent = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "worker.invitation_resent")
        )
    ).one()
    assert resent.before == {"full_name": "Grace Owusu", "data_region": "GH", "worker_type": "freelancer"}
    assert resent.after == {"full_name": "Grace A. Owusu", "data_region": "EU", "worker_type": "freelancer"}


async def test_resends_are_limited_per_hour(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, pm)
    await client.post(URL, json=BODY, headers=headers)
    statuses = [(await client.post(URL, json=BODY, headers=headers)).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


async def test_revoked_invited_account_is_not_resent(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    headers = bearer(settings, pm)
    await client.post(URL, json=BODY, headers=headers)
    account = (
        await session.scalars(select(UserAccount).where(UserAccount.role == UserRole.WORKER))
    ).one()
    account.status = AccountStatus.REVOKED
    await session.commit()

    response = await client.post(URL, json=BODY, headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "email_in_use"


async def test_openapi_documents_the_resend_response(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()

    responses = spec["paths"]["/api/v1/workers/invitations"]["post"]["responses"]
    assert {"200", "201"} <= set(responses)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/passport -v`
Expected: the new tests FAIL (422 without a code, 500 on the races, resend not updating/limiting, revoked account resent, OpenAPI missing 200).

- [ ] **Step 3: Implement**

In `backend/app/core/errors.py`, add after `Conflict`:

```python
class UnprocessableEntity(AppError):
    status_code = 422
    code = "unprocessable"
    title = "Unprocessable request"
```

In `backend/app/modules/passport/schemas.py`, in `WorkerUpdate._consistent`, delete the two availability checks (keep the null-guard loop). The validator now only rejects explicit nulls for required fields.

In `backend/app/modules/passport/profile.py`, in `update_self`, replace the availability block with a merged-state check before applying changes:

```python
        changes = data.model_dump(exclude_unset=True)
        status = changes.get("availability_status", worker.availability_status)
        if "availability_status" in changes and status is not AvailabilityStatus.AVAILABLE_FROM:
            changes["available_from"] = None
        available_from = changes.get("available_from", worker.available_from)
        if status is AvailabilityStatus.AVAILABLE_FROM and available_from is None:
            raise UnprocessableEntity(
                "available_from is required with availability_status=available_from",
                code="availability_date_required",
            )
        if available_from is not None and status is not AvailabilityStatus.AVAILABLE_FROM:
            raise UnprocessableEntity(
                "available_from needs availability_status=available_from",
                code="availability_status_mismatch",
            )
```

(import `UnprocessableEntity`; keep the existing `setattr` loop and event emission after this block).

In `backend/app/modules/passport/skills.py`, wrap each insert in a savepoint and map only the expected constraint (imports: `IntegrityError`, `violated_constraint`):

```python
        try:
            async with self.session.begin_nested():
                skill = self.skills.add(Skill(slug=data.slug, name_i18n=names))
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_skills_slug":
                raise
            raise Conflict("A skill with this slug exists", code="skill_slug_taken") from exc
```

and in `ClaimService.claim`:

```python
        try:
            async with self.session.begin_nested():
                claim = self.claims.add(
                    SkillClaim(
                        worker_id=who.worker_id,
                        skill_id=skill_id,
                        verification_status=VerificationStatus.SELF_REPORTED,
                        source=ClaimSource.SELF,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_skill_claims_worker_skill":
                raise
            raise Conflict("You already list this skill", code="skill_already_claimed") from exc
```

In `backend/app/modules/identity/accounts.py`, make `find_worker_account` return `None` unless `user.status is AccountStatus.ACTIVE` (add that condition to its existing role/worker_id check).

In `backend/app/modules/passport/invitations.py`:
- Add `INVITATION_RESENDS_PER_HOUR = 3`.
- Pass `data` into `_resend_if_still_invited(actor, email, data)`.
- In `_resend_if_still_invited`, after the `onboarding_state` check and before writing the audit row:

```python
        since = utcnow() - timedelta(hours=1)
        recent = await self.session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "worker.invitation_resent",
                AuditLog.target_id == worker.id,
                AuditLog.occurred_at >= since,
            )
        )
        if (recent or 0) >= INVITATION_RESENDS_PER_HOUR:
            raise TooManyRequests(
                "This invitation was resent too often; try again later",
                code="invitation_resend_limited",
            )
        before = {
            "full_name": worker.full_name,
            "data_region": worker.data_region,
            "worker_type": worker.worker_type.value,
        }
        worker.full_name = data.full_name.strip()
        worker.data_region = data.data_region
        worker.worker_type = data.worker_type
        after = {
            "full_name": worker.full_name,
            "data_region": worker.data_region,
            "worker_type": worker.worker_type.value,
        }
```

  and write the `worker.invitation_resent` audit row with `before=before, after=after` (names and regions are not contact data). Imports: `timedelta`, `func, select`, `AuditLog` (from `app.core.audit.models` — core is importable from modules), `TooManyRequests`, `utcnow`.

In `backend/app/modules/passport/router.py`, add `responses={200: {"model": InvitationRead, "description": "Invitation resent"}}` to the `@router.post("/workers/invitations", ...)` decorator.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/passport tests/api/identity -v`
Expected: all pass.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests
git commit -m "fix(passport): merged availability checks, race-safe uniqueness, invitation resend polish"
```

---

### Task 10: Identity and core carry-forward fixes

**Files:**
- Modify: `backend/app/modules/identity/grants.py`, `backend/app/modules/identity/accounts.py`, `backend/app/modules/identity/scim.py`, `backend/pyproject.toml`
- Test: `backend/tests/api/identity/test_scim.py`

**Interfaces:**
- Consumes: `violated_constraint` (Task 3).
- Produces: `GrantService.create` maps only `fk_access_grants_scoped_worker_id`; `provision_worker_account` maps only `uq_user_accounts_email`; SCIM strips the core-schema URN prefix (`urn:ietf:params:scim:schemas:core:2.0:User:`) before normalizing and rejects other `urn:` paths that end in a managed attribute; coverage measures greenlet concurrency.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/identity/test_scim.py`:

```python
URN = "urn:ietf:params:scim:schemas:core:2.0:User:"


async def test_fully_qualified_active_path_deactivates(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await _pm_with_session(session, settings)

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch({"op": "replace", "path": f"{URN}active", "value": False}),
        headers=SCIM,
    )

    assert response.status_code == 200
    await session.refresh(user)
    assert user.status is AccountStatus.REVOKED


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "remove", "path": f"{URN}roles"},
        {"op": "replace", "path": "urn:example:custom:2.0:User:active", "value": False},
    ],
)
async def test_urn_paths_to_managed_attributes_are_never_silently_ignored(
    client: AsyncClient, session: AsyncSession, operation: dict[str, object]
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama", json=_patch(operation), headers=SCIM
    )

    assert response.status_code == 400
    assert response.json()["code"] == "scim_unsupported_operation"


async def test_enterprise_extension_attributes_are_still_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, oidc_subject="kc-ama")

    response = await client.patch(
        "/api/v1/scim/v2/Users/kc-ama",
        json=_patch(
            {
                "op": "replace",
                "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:manager",
                "value": {"value": "someone"},
            }
        ),
        headers=SCIM,
    )

    assert response.status_code == 200
```

(Use the names that exist in the file — `_pm_with_session`, `_patch`, `SCIM`, `make_user`; import `pytest` if not already.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/identity/test_scim.py -v`
Expected: the URN tests FAIL (URN active path ignored → still active; other URN path returns 200).

- [ ] **Step 3: Implement**

In `backend/app/modules/identity/scim.py`, add before `_normalize` (and use it at the start of `_normalize`):

```python
_CORE_USER_URN = "urn:ietf:params:scim:schemas:core:2.0:user:"


def _strip_urn(path: str) -> str:
    """RFC 7644 §3.10 allows fully qualified paths. Strip the core User schema;
    for any other URN keep only the attribute after the last ':' so a managed
    attribute in a foreign schema is rejected rather than silently ignored."""
    lowered = path.lower()
    if lowered.startswith(_CORE_USER_URN):
        return path[len(_CORE_USER_URN):]
    if lowered.startswith("urn:"):
        attribute = path.rsplit(":", 1)[-1]
        if attribute.split("[")[0].split(".")[0].lower() in _MANAGED_PATHS:
            raise _unsupported(f"'{path}' is not a supported attribute path")
    return path
```

and change `_normalize` to apply `_strip_urn(path)` before its existing `split("[")…lower()` logic (None still maps to None). Where `_interpret` checks the raw path for `[` or `.` on managed attributes, check the URN-stripped path instead (otherwise the `.` in `2.0` would trip it).

In `backend/app/modules/identity/grants.py`, change the `except IntegrityError` block to:

```python
        except IntegrityError as exc:
            if violated_constraint(exc) != "fk_access_grants_scoped_worker_id":
                raise
            raise BadRequest("No worker with this id", code="grant_worker_not_found") from exc
```

In `backend/app/modules/identity/accounts.py` (`provision_worker_account`), likewise:

```python
    except IntegrityError as exc:
        if violated_constraint(exc) != "uq_user_accounts_email":
            raise
        raise Conflict("An account with this email already exists", code="email_in_use") from exc
```

(import `violated_constraint` from `app.core.db.errors` in both).

Add to `backend/pyproject.toml`:

```toml
[tool.coverage.run]
# SQLAlchemy's async engine runs sync work in greenlets; without this,
# coverage misses lines after awaits in async services.
concurrency = ["greenlet", "thread"]
```

Confirm `greenlet` is installed (`pip show greenlet`), then record coverage before and after for `app/modules/passport/invitations.py` in the report.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/identity -v` then `pytest --cov=app --cov-report=term-missing | grep -E "invitations|profile|TOTAL"`
Expected: all pass; the async passport services show materially higher coverage than before.

- [ ] **Step 5: Full check and commit**

```bash
ruff format . && ruff check . && mypy && lint-imports && pytest
git add app tests pyproject.toml
git commit -m "fix(identity): SCIM URN paths, constraint-specific integrity errors; coverage greenlets"
```

---

### Task 11: End-to-end reactivation loop, roadmap and docs

**Files:**
- Create: `backend/tests/api/test_reactivation_loop.py`
- Modify: `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`, `PROJECT_STRUCTURE.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the end-to-end test**

`backend/tests/api/test_reactivation_loop.py`:

```python
"""The MVA's core loop (spec §10): a first-time worker is invited, onboards,
is engaged and signs; a different PM later reactivates them with prefilled
terms, and the new engagement appears on the worker's own passport."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.integrations.service import FakeEsignAdapter, FakePayrollAdapter
from app.modules.passport.models import Skill
from tests.support import (
    RecordingMailer,
    bearer,
    engagement_terms,
    esign_webhook,
    make_project,
    make_user,
)

Drain = Callable[[], Awaitable[None]]
ANSWERS = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": True,
    "would_reengage": True,
}


async def test_invite_engage_complete_and_reactivate(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    mailer: RecordingMailer,
    drain: Drain,
    esign: FakeEsignAdapter,
    payroll: FakePayrollAdapter,
) -> None:
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    first_project = await make_project(session, staff=[ama], name="Volta")
    second_project = await make_project(session, staff=[kwame], name="Tema")
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.commit()

    # 1. Ama invites Kofi; Kofi signs in and completes onboarding.
    invited = await client.post(
        "/api/v1/workers/invitations",
        json={
            "email": "kofi@example.com",
            "full_name": "Kofi Mensah",
            "worker_type": "freelancer",
            "data_region": "GH",
        },
        headers=bearer(settings, ama),
    )
    worker_id = invited.json()["worker_id"]
    await drain()
    token = (
        await client.post("/api/v1/auth/magic-link/verify", json={"token": mailer.token()})
    ).json()["access_token"]
    kofi = {"Authorization": f"Bearer {token}"}
    await client.patch(
        "/api/v1/workers/me", json={"base_location": "Accra", "languages": ["en"]}, headers=kofi
    )
    await client.post("/api/v1/workers/me/skills", json={"skill_id": str(skill.id)}, headers=kofi)
    onboarded = await client.post("/api/v1/workers/me/onboarding/complete", headers=kofi)
    assert onboarded.json()["onboarding_state"] == "profile_complete"

    # 2. Ama engages Kofi (first time); the contract goes out and is signed.
    first = await client.post(
        f"/api/v1/workers/{worker_id}/engagements",
        json=engagement_terms(first_project.id),
        headers=bearer(settings, ama),
    )
    assert first.json()["path"] == "first_time"
    await drain()
    envelope = esign.sent[next(iter(esign.sent))]
    body, headers = esign_webhook(
        settings, {"envelope_id": f"fake-env-{envelope.engagement_id}", "event": "signed"}
    )
    assert (await client.post("/api/v1/webhooks/esign", content=body, headers=headers)).status_code == 204
    await drain()
    assert len(payroll.activations) == 1
    assert (await client.get("/api/v1/workers/me", headers=kofi)).json()["status"] == "active"

    # 3. Ama completes the engagement and leaves feedback.
    await client.post(
        f"/api/v1/engagements/{first.json()['id']}/complete", json={}, headers=bearer(settings, ama)
    )
    await client.post(
        f"/api/v1/engagements/{first.json()['id']}/feedback",
        json={"structured_answers": ANSWERS, "skill_ids_demonstrated": [str(skill.id)]},
        headers=bearer(settings, ama),
    )
    await drain()
    assert (await client.get("/api/v1/workers/me", headers=kofi)).json()["status"] == "dormant"

    # 4. Kwame, who never worked with Kofi, reactivates him with prefilled terms.
    prefill = await client.get(
        f"/api/v1/workers/{worker_id}/reactivation-prefill",
        params={"project_id": str(second_project.id)},
        headers=bearer(settings, kwame),
    )
    assert prefill.json()["prefilled_from_engagement_id"] == first.json()["id"]
    terms = prefill.json()
    reactivated = await client.post(
        f"/api/v1/workers/{worker_id}/reactivations",
        json=engagement_terms(
            second_project.id,
            rate=terms["rate"],
            work_mode=terms["work_mode"],
            contract_terms=terms["contract_terms"],
            prefilled_from_engagement_id=terms["prefilled_from_engagement_id"],
        ),
        headers=bearer(settings, kwame) | {"Idempotency-Key": "kwame-reactivates-kofi"},
    )
    assert reactivated.status_code == 201
    assert reactivated.json()["path"] == "reactivation"
    await drain()

    # 5. The same records appear on Kofi's own passport (FR-4.5).
    history = await client.get(f"/api/v1/workers/{worker_id}/engagements", headers=kofi)
    assert [e["path"] for e in history.json()] == ["reactivation", "first_time"]
    assert history.json()[1]["feedback"]["structured_answers"] == ANSWERS
    assert len(esign.sent) == 2
```

Run: `pytest tests/api/test_reactivation_loop.py -v`
Expected: PASS (all behaviour exists by now; if it fails, the failure points to an integration gap between earlier tasks — fix it in the task's module and note it in the report).

- [ ] **Step 2: Update the roadmap**

In `docs/superpowers/plans/2026-09-22-bonarda-00-roadmap.md`:
- Plan 2B row: file `2026-09-24-bonarda-02b-engagements.md`, status `Written`.
- Delete the carry-forward rows this plan closed: `AccessRevoked` → `project_staff`; IntegrityError narrowing; skill slug/claim 409; onboarding re-check at first-time engagement; `data_region` validation; merged-state availability; invitation resend polish; SCIM URN paths; coverage greenlet concurrency.
- Add carry-forward rows:
  - 6 | Fake e-sign never signs by itself; for the demo add auto-sign after a delay (or a dev-only sign endpoint) so the loop runs without a provider.
  - 4 | Worker and PM notifications: "engagement confirmed" to the worker on activation and "feedback due" to the PM on completion (spec §7.7 `notify_worker`, `notify_feedback_due`).
  - 4 | Close a project (`status=closed`); no endpoint yet, so every project stays active.
  - any | Finance has `engagement:read_billing` but no billing read endpoint yet.
- Add deviation rows:
  - 2B | Engagement routes address the worker in the path: `POST /workers/{id}/engagements`, `GET /workers/{id}/reactivation-prefill`, `POST /workers/{id}/reactivations`; managed actions are `/engagements/{id}/complete`, `/feedback`, `/contract/retry` (not `:complete`/`:retry`) | Visibility guard coverage; plain REST paths
  - 2B | Reactivation prefill needs summary visibility, not detail, and returns contract terms only | A new PM reactivating someone another PM worked with (FR-4.3's core case) only has summary visibility
  - 2B | A worker with any non-cancelled engagement can only be engaged through reactivation | Keeps first-time vs repeat metrics (FR-5.3) accurate
- Change the 2A deviation "the inviting PM gets 404 … until Plan 2B adds PM visibility sources" to note it is resolved in 2B (the inviting PM sees the summary when they staff a project in the worker's region).

- [ ] **Step 3: Update PROJECT_STRUCTURE.md**

Replace the `engagements/` line under `modules/` with:

```
│   │   │   ├── engagements/               # projects, staffing, engagements, contracts, feedback (Plan 2B)
│   │   │   │   ├── enums.py, models.py, repository.py, schemas.py
│   │   │   │   ├── projects.py, visibility.py, engagements.py, contracts.py
│   │   │   │   ├── payroll.py, feedback.py, stuck.py, handlers.py
│   │   │   │   ├── router.py
│   │   │   │   └── service.py
```

and under `integrations/` list `esign.py`, `payroll.py`, `webhooks.py` next to `smtp.py`.

- [ ] **Step 4: Full verification**

Run: `ruff format --check . && ruff check . && mypy && lint-imports && pytest --cov=app --cov-report=term-missing`
Expected: all pass; record the test count and coverage in the commit body.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend docs PROJECT_STRUCTURE.md
git commit -m "test: end-to-end reactivation loop; record Plan 2B in roadmap and docs"
```

---

## Spec coverage for this plan

| Spec / carry-forward item | Task |
|---|---|
| §6.1 `projects`, `project_staff`, `engagements`, `feedback`; §6.4 engagement indexes | 1, 2 |
| §7.1 PM visibility (detail via engagement on a staffed project; summary via region/consent) | 2 |
| §7.2 projects, staffing, first-time engagement, prefill, reactivation, complete, feedback, contract retry, e-sign webhook | 1, 3, 4, 6, 7 |
| §7.5 reactivation sequence (one transaction, outbox dispatch, webhook, payroll) | 4, 6 |
| §7.6 `AccessRevoked` ends `project_staff` | 1 |
| §7.7 handlers and crons: send_contract, activate_due (hourly), signal_payroll, stuck detector (15 min), worker status sync | 6, 7, 8 |
| §8.1 webhook HMAC + timestamp; §8.4 idempotency key, handler dedupe, adapter idempotency | 4, 5, 6 |
| FR-2.3/2.4 structured feedback, visible to the worker; FR-4.2 last time-to-start; FR-4.4/4.5; FR-5.1/5.3; FR-8.2/8.3; FR-9.7 dormant | 3, 4, 6, 7 |
| Carry-forward: `AccessRevoked` → staffing; region validation; onboarding re-check | 1, 3 |
| Carry-forward: merged availability; slug/claim 409; invitation resend polish | 9 |
| Carry-forward: IntegrityError narrowing; SCIM URN paths; coverage greenlets | 3, 10 |

Deferred (recorded in Task 11): fake e-sign auto-sign for the demo (Plan 6), worker/PM notifications (Plan 4), project closing (Plan 4), finance billing read. Plan 3 consumes `FeedbackSubmitted` and `WorkerUpdated` for standing and the roster.

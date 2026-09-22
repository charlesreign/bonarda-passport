# Bonarda Works — Project Root Structure & Setup Guide

Companion to `bonarda-requirements.md` and `bonarda-system-design.md`. This document defines the repository layout for the modular-monolith FastAPI backend and the React frontend, plus the steps to get both running locally.

---

## 1. Repository layout

```
bonarda-passport/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app factory, router registration
│   │   ├── core/
│   │   │   ├── config.py              # Pydantic Settings — env-driven config
│   │   │   ├── security.py            # JWT issuance/validation, magic-link, SSO token checks
│   │   │   └── logging.py             # structlog configuration
│   │   ├── db/
│   │   │   ├── session.py             # async engine + session factory
│   │   │   └── base.py                # SQLAlchemy declarative base
│   │   ├── models/                    # SQLAlchemy ORM models (one file per entity)
│   │   │   ├── worker.py
│   │   │   ├── engagement.py
│   │   │   ├── skill_claim.py
│   │   │   ├── standing_change.py
│   │   │   ├── dispute.py
│   │   │   ├── user_account.py
│   │   │   └── access_grant.py
│   │   ├── schemas/                   # Pydantic request/response models (separate from ORM)
│   │   │   ├── worker.py
│   │   │   ├── engagement.py
│   │   │   ├── feedback.py
│   │   │   └── auth.py
│   │   ├── repositories/              # data-access layer — the missing piece
│   │   │   ├── base.py                # generic CRUD repository, typed on the model
│   │   │   ├── worker_repository.py
│   │   │   ├── engagement_repository.py
│   │   │   ├── skill_claim_repository.py
│   │   │   ├── dispute_repository.py
│   │   │   ├── standing_change_repository.py
│   │   │   └── access_grant_repository.py
│   │   ├── routers/                   # one module per FR-6.x domain
│   │   │   ├── auth.py
│   │   │   ├── workers.py
│   │   │   ├── roster.py              # includes /roster/first-shot (FR-4.6)
│   │   │   ├── engagements.py
│   │   │   ├── feedback.py
│   │   │   ├── disputes.py
│   │   │   ├── governance.py
│   │   │   └── access.py
│   │   ├── services/                  # business logic, kept out of routers
│   │   │   │                          # — calls repositories, never the ORM/session directly
│   │   │   ├── tiering.py             # FR-3.1–3.3 rules engine
│   │   │   ├── matching.py            # FR-6.1 recommendation logic
│   │   │   └── reactivation.py
│   │   ├── integrations/              # provider-agnostic adapters (ambiguity #5)
│   │   │   ├── esign/
│   │   │   │   ├── base.py            # adapter interface
│   │   │   │   └── docusign_adapter.py
│   │   │   ├── payroll/
│   │   │   └── sso/
│   │   ├── workers/                   # Arq job definitions
│   │   │   ├── settings.py            # Arq WorkerSettings, cron schedule
│   │   │   └── jobs.py                # send_contract, notify_worker, recalculate_tier, etc.
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_routers/
│   │       ├── test_services/         # mock repositories — no real DB needed
│   │       └── test_repositories/     # real test-DB integration tests
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── alembic.ini
│   ├── pytest.ini
│   ├── pyproject.toml                 # ruff/mypy config
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── providers/
│   │   │   ├── AuthProvider.tsx
│   │   │   └── QueryProvider.tsx
│   │   ├── hooks/
│   │   │   ├── useWorkerProfile.ts
│   │   │   ├── useReactivation.ts
│   │   │   ├── useRosterSearch.ts
│   │   │   └── useConcentrationMetrics.ts
│   │   ├── components/
│   │   │   ├── pm-console/
│   │   │   │   ├── RosterList.tsx
│   │   │   │   ├── FirstShotPanel.tsx
│   │   │   │   └── ReactivationFlow.tsx
│   │   │   ├── passport/
│   │   │   │   ├── PassportSpread.tsx
│   │   │   │   └── EngagementStampGrid.tsx
│   │   │   └── governance/
│   │   │       └── ConcentrationDashboard.tsx
│   │   ├── api/                       # typed fetch client, generated from OpenAPI
│   │   ├── types/                     # shared TS types
│   │   ├── pages/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── Dockerfile
│   └── .env.example
│
├── infra/
│   ├── docker-compose.yml             # postgres, redis, api, worker, frontend
│   └── k8s/                           # deferred past MVA — manifests scaffolded only
│
├── docs/
│   ├── bonarda-requirements.md
│   ├── bonarda-system-design.md
│   └── PROJECT_STRUCTURE.md
│
├── .github/
│   └── workflows/
│       └── ci.yml                     # lint, type-check, test on PR
│
├── .env.example                       # root-level shared vars (compose)
├── .gitignore
└── README.md
```

**Design notes**

- `routers/`, `services/`, `repositories/`, and `integrations/` form a strict one-way dependency chain: **routers → services → repositories → models**. A router never queries the database directly, and a service never imports SQLAlchemy's `select()` or touches an `AsyncSession` directly — it calls a repository method instead. This is what makes `services/` (§6, business rules like FR-3.1–3.3's tiering) unit-testable with an in-memory fake repository, with no real database needed for that test tier.
- `repositories/` is the data-access layer — one repository per aggregate (`WorkerRepository`, `EngagementRepository`, etc.), each wrapping the actual SQLAlchemy queries for that entity behind a typed, intention-revealing method (`get_active_by_id`, `list_by_worker_ordered_by_date`) rather than services building ad hoc queries inline. `repositories/base.py` provides a generic typed CRUD base (`get`, `list`, `create`, `update`, `delete`) that entity-specific repositories extend with their own query methods:

  ```python
  # backend/app/repositories/base.py
  from typing import Generic, TypeVar
  from uuid import UUID

  from sqlalchemy import select
  from sqlalchemy.ext.asyncio import AsyncSession

  from app.db.base import Base

  ModelT = TypeVar("ModelT", bound=Base)

  class BaseRepository(Generic[ModelT]):
      model: type[ModelT]

      def __init__(self, session: AsyncSession) -> None:
          self.session = session

      async def get(self, id: UUID) -> ModelT | None:
          return await self.session.get(self.model, id)

      async def create(self, obj: ModelT) -> ModelT:
          self.session.add(obj)
          await self.session.flush()
          return obj
  ```

  ```python
  # backend/app/repositories/worker_repository.py
  from sqlalchemy import select

  from app.models.enums import WorkerStatus
  from app.models.worker import Worker
  from app.repositories.base import BaseRepository

  class WorkerRepository(BaseRepository[Worker]):
      model = Worker

      async def search_active(self, *, skill: str | None, location: str | None) -> list[Worker]:
          """Backs GET /roster/search (FR-4.1) — the only place this
          query is written, so an index change or query rewrite touches
          one file, not every router that happens to need a worker list."""
          stmt = select(Worker).where(Worker.status == WorkerStatus.ACTIVE)
          if skill:
              stmt = stmt.join(Worker.skill_claims).where(...)
          if location:
              stmt = stmt.where(Worker.base_location == location)
          result = await self.session.execute(stmt)
          return list(result.scalars().all())
  ```

  A service then depends on the repository, not the session:

  ```python
  # backend/app/services/reactivation.py
  class ReactivationService:
      def __init__(self, worker_repo: WorkerRepository, engagement_repo: EngagementRepository) -> None:
          self.worker_repo = worker_repo
          self.engagement_repo = engagement_repo

      async def reactivate(self, worker_id: UUID, project_id: UUID) -> Engagement:
          worker = await self.worker_repo.get(worker_id)
          # ...business rules here, no SQL in sight
  ```

  Swapping in a `FakeWorkerRepository` (a plain in-memory dict) for `ReactivationService` tests means the tiering and reactivation business rules can be tested without a Postgres instance at all — that speed matters given how often `services/` changes relative to `repositories/`.

- `models/` and `schemas/` are kept as separate directories on purpose (System Design §4) — the API contract in `schemas/` should be able to evolve independently of the database shape in `models/`. `repositories/` returns ORM models, not schemas — the router layer is responsible for converting a repository's `Worker` into a `WorkerRead` schema, keeping that translation in exactly one place.
- `integrations/` third-party calls are isolated behind an adapter interface — this is what lets the e-signature or SSO provider change without touching business logic (System Design §2, ambiguity #5).
- `workers/jobs.py` holds every Arq job named in the System Design §6.3 table, each triggered from a service layer call (which itself goes through a repository), never directly from a router.

---

## 2. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Backend runtime |
| Node.js | 20+ (LTS) | Frontend tooling |
| Docker & Docker Compose | Latest | Local Postgres/Redis, containerized dev parity |
| PostgreSQL | 16 | Primary datastore (via Docker unless installed natively) |
| Redis | 7 | Cache + Arq queue (via Docker unless installed natively) |

---

## 3. Local setup — fastest path (Docker Compose)

```bash
git clone <repo-url> bonarda-passport
cd bonarda-passport

cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# fill in secrets: SSO client id/secret, e-signature API key, DB creds

docker compose -f infra/docker-compose.yml up --build
```

This brings up Postgres, Redis, the FastAPI API, the Arq worker, and the React dev server together. API docs are available at `http://localhost:8000/docs` once the container is healthy.

---

## 4. Local setup — running services natively (for backend/frontend development without full container rebuilds)

### 4.1 Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env               # point DATABASE_URL / REDIS_URL at local or Docker services

alembic upgrade head                # apply migrations

uvicorn app.main:app --reload --port 8000
```

Run the background worker in a second terminal (same virtualenv):

```bash
arq app.workers.settings.WorkerSettings
```

Run tests:

```bash
pytest
ruff check .
mypy app
```

### 4.2 Frontend

```bash
cd frontend
npm install
cp .env.example .env               # set VITE_API_BASE_URL=http://localhost:8000

npm run dev                        # starts Vite dev server, default port 5173
```

---

## 5. Environment variables (summary)

| Variable | Where | Purpose |
|---|---|---|
| `DATABASE_URL` | backend | asyncpg connection string |
| `REDIS_URL` | backend | cache + Arq queue |
| `JWT_SECRET` / `JWT_ALGORITHM` | backend | access/refresh token signing |
| `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET` / `SSO_ISSUER_URL` | backend | corporate OIDC (FR-9.1) |
| `ESIGN_PROVIDER` / `ESIGN_API_KEY` | backend | selected via adapter interface — provider swappable |
| `PAYROLL_WEBHOOK_URL` / `PAYROLL_API_KEY` | backend | engagement-activation signal |
| `VITE_API_BASE_URL` | frontend | API base URL the SPA calls |

Never commit a filled `.env` — only `.env.example` with placeholder values is checked in.

---

## 6. Database migrations

New migration after a model change:

```bash
cd backend
alembic revision --autogenerate -m "add dispute status index"
alembic upgrade head
```

Every migration is reviewed in PR like any other code change — this is the mechanism behind NFR-3.3's requirement that schema changes remain traceable.

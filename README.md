# Bonarda Works — Freelancer Passport

A FastAPI modular monolith (PostgreSQL, Redis, Arq, transactional outbox) with a
React console. Design: `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`.

## Run the demo

Requires Docker.

```bash
docker compose up --build
```

| What | Where |
|---|---|
| App | http://localhost:8080 |
| Mail (magic links, notifications) | http://localhost:8025 (Mailpit) |
| API docs | http://localhost:8000/docs |

The API container migrates the database and seeds a demo dataset on first start:
- 6 staff accounts;
- 24 freelancers in Ghana and the EU, with history, tiers and verified skills;
- 3 live projects;
- one open dispute.

Reset everything with `docker compose down -v`.

Sign in from the **Demo accounts** panel (demo mode only; staff normally use the
company IdP). Freelancers can also use a real magic link: enter e.g.
`yaw@example.com` and open the mail in Mailpit.

### A five-minute walkthrough

1. **Efua (PM) → Volta Retail Analytics.**
   - **Candidates:** scored, with a breakdown (verified skills, self-reported skills, availability, and tier capped at 15%).
   - **First shot:** qualified people with little recent work, on the same page as the candidates and always shown.
2. **Reactivate Yaw Darko.**
   - Open Yaw from the candidates. The terms are prefilled from his last engagement.
   - Confirm. The worker process sends the contract, and the drawer shows it awaiting Yaw's signature.
   - Sign in as **Yaw** in another browser or a private window. His passport shows **Contract ready for your signature**. Click **Sign contract**. This demo step stands in for the e-sign provider's email, and only the freelancer on the contract can use it.
   - Back as Efua, the engagement is active without a reload. **Mark completed**, then **Give feedback**.
3. **Shortlist someone in First shot.** This gives you detail visibility of that person; **Pass** needs a reason code.
4. **Yaw (freelancer) → My passport.**
   - The engagement and its feedback appear right away (the same record the PM sees).
   - My standing shows the tier, the signals behind it, the policy version and the history.
   - Any record can be disputed from there.
5. **Ama (People Ops) → Governance.**
   - Resolve Esi's dispute. Upholding stops that feedback counting toward her standing.
   - Override a tier (a reason is required).
   - Browse the audit log. Policies shows matching v2, which the seed activated through two-person approval.
6. **Mailpit** shows the notifications: engagement started, feedback due, standing changed, dispute resolved.

## Develop

Backend (from `backend/`, Python 3.12, Docker running for Testcontainers):

```bash
python -m venv .venv && source .venv/Scripts/activate   # or bin/activate
pip install -r requirements-dev.txt
ruff format . && ruff check . && mypy && lint-imports && pytest
```

Frontend (from `frontend/`): `npm install && npm run dev`. Vite proxies `/api` to `localhost:8000`,
so run the API with `DEMO_MODE=true` (and the rest of `.env.example`) for the demo sign-in.

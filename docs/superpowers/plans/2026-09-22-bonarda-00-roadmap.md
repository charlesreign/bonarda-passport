# Bonarda Works Passport — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`

The spec's MVA (§10) is delivered as six sequential plans. Each plan ends with working, tested software and is written in full only when its predecessor is merged, so it can build on the real code rather than on guesses.

| # | Plan | Delivers | Depends on | Status |
|---|---|---|---|---|
| 1 | `2026-09-22-bonarda-01-backend-foundation.md` | Backend scaffold, CI checks, shared kernel (settings, DB, problem+json errors, correlation IDs, audit writer, transactional outbox, relay, idempotent handlers, Arq worker), `identity` module (access/refresh tokens, magic links, staff OIDC with MFA check, role permission matrix, `VisibilityPolicy`, access grants, SCIM revocation) | — | Implemented on `feat/backend-foundation` |
| 2A | `2026-09-23-bonarda-02a-worker-passport.md` | `passport` (workers, skills taxonomy and claims, profile views, onboarding, consents, PM invitations), SMTP mailer, sign-in mail sent by the worker, per-account locale, Plan 1 identity carry-forward fixes | 1 | Implemented on `feat/worker-passport` |
| 2B | `2026-09-24-bonarda-02b-engagements.md` | `engagements` (projects, staffing, first-time engagements, reactivation prefill and create, contracts via fake e-sign, e-sign webhook, payroll signal, completion, feedback, stuck detector), e-sign/payroll adapters, PM visibility sources, `AccessRevoked` → end `project_staff` | 2A | Written |
| 3 | `…-03-fairness-engine.md` | `policy_configs` with two-person activation, `standing` (rules engine, skill evidence, append-only standing changes), `roster` (read-model, scoring, first-shot, impression logging) | 2B | Not written |
| 4 | `…-04-governance.md` | Disputes with SLA, standing overrides, concentration rollups and alerts, audit-log API, retention enforcement and anonymization | 3 | Not written |
| 5 | `…-05-frontend.md` | Vite/React app: generated API client, providers, `/passport`, `/console`, `/ops` bundles, i18n (en/fr), size budgets, Playwright + axe | 1–4 (API contract) | Not written |
| 6 | `…-06-demo-and-operations.md` | Docker Compose with Keycloak + Mailpit, real `AuthlibOidcProvider` verification against Keycloak, seed data, Prometheus metrics and custom counters, Locust profile | 1–5 | Not written |

Pre-live gates (spec §10) — SCIM wired to the real IdP, real e-sign/payroll adapters, penetration test, legal sign-offs — are outside these plans.

## Carry-forward from Plan 1 (review findings deferred to later plans)

Each item below must become a named task with a test in the plan listed.

| Plan | Item |
|---|---|
| 4 | Grant revocation takes no `reason`; logout audit uses `actor=None` though the user is known; move the SSO-login audit from the router into `OidcLoginService`. |
| 6 | Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` so per-IP magic-link limits see real client IPs. |
| 6 | SMTP mailer selection is done (`SMTP_URL`, TLS required outside dev/test; `create_app` refuses ConsoleMailer outside dev/test). What remains: Mailpit in Compose, and a dead-letter consumer with alerting. Verify `AuthlibOidcProvider` against Keycloak; map IdP/network failures to `oidc_error`. |
| 6 | Outbox relay polish: wait on `stop` as well as `wake` during backoff (shutdown can block ≤30 s); close the connection if `add_listener` fails; add a connect timeout; one permanently failing event holds the relay in 30 s backoff — consider per-row backoff. |
| 6 | Add metrics `outbox_lag_seconds`, `dead_letter_total` and alerts (spec §8.3). |
| any | Async tests: never write `session.expire_all()` + `session.get()` (raises MissingGreenlet) — use `await session.refresh(obj)`. |
| any | FastAPI is pinned to 0.115.0 because `get_session` relies on yield-dependency teardown running before the response is sent; re-verify before upgrading. |
| 4 | Consent and onboarding audit rows carry only `after`, no `before`. |
| 6 | Outbox handler retry budget (~30 s over 5 tries) is too short for SMTP outages; lengthen for mail handlers and add a dead-letter consumer with alerting. |
| 4 | Audit `full_name` changes (`worker.renamed`, before/after) before contracts print it; don't emit `WorkerUpdated` for no-op PATCHes. |
| 5 | Type `locale` response fields as the `Locale` enum (`MeResponse`, `AccountContact`, `WorkerSelf`) for the generated client. |
| any | Visibility guard compares Python field names only: aliases (`Field(alias="worker_id")`), untyped `dict` bodies and unresolved forward references are not detected. |
| 6 | Fake e-sign never signs by itself; for the demo add auto-sign after a delay (or a dev-only sign endpoint) so the loop runs without a provider. |
| 4 | Worker and PM notifications: "engagement confirmed" to the worker on activation and "feedback due" to the PM on completion (spec §7.7 `notify_worker`, `notify_feedback_due`). |
| 4 | Close a project (`status=closed`); no endpoint yet, so every project stays active. |
| 4 | Closing a project must end its open `project_staff` rows. Staff rows on a closed project otherwise keep granting worker visibility. |
| any | Finance has `engagement:read_billing` but no billing read endpoint yet. |
| any | `sync_worker_status` counts active engagements and then writes the worker row without a lock. A concurrent cancel and activate can leave the worker dormant even though it has an active engagement. |
| any | `billable_start_at` is stamped when the job runs. It should be max(signed_at, start_date at 00:00 UTC). |

## Implementation deviations from the spec (recorded as they happen)

| Plan | Deviation | Reason |
|---|---|---|
| 1 | Refresh cookie path is `/api/v1/auth`, not `/api/v1/auth/refresh` | Logout must receive the cookie too |
| 2A | `workers` has no `email`/`locale`; both live on `user_accounts` (locale for every account) | One source of truth; PMs need a locale too (NFR-8.2) |
| 2A | Worker-scoped routes put the worker in the path (`/workers/{worker_id}/…`); request bodies never carry `worker_id` | Every worker route passes through the visibility guard, enforced in CI |
| 2A | Staff roles come only from the IdP (SCIM push + OIDC login reconcile), and any role change revokes existing sessions | Single role authority; no stale-role devices |
| 2A | Locale is edited via `PATCH /me` (all accounts), not `PATCH /workers/me` | Locale lives on the account; `WorkerUpdate` forbids it |
| 2A | Invitations are not yet tied to a project; the inviting PM gets 404 on `GET /workers/{id}` until Plan 2B adds PM visibility sources — resolved in 2B: the inviting PM sees the summary when they staff a project in the worker's region | Projects arrive in Plan 2B |
| 2A | Re-inviting a worker still at `invited` resends the invitation (200) instead of 409 | Recovery path for lost invitation emails |
| 2B | Engagement routes address the worker in the path: `POST /workers/{id}/engagements`, `GET /workers/{id}/reactivation-prefill`, `POST /workers/{id}/reactivations`; managed actions are `/engagements/{id}/complete`, `/feedback`, `/contract/retry` (not `:complete`/`:retry`) | Visibility guard coverage; plain REST paths |
| 2B | Reactivation prefill needs summary visibility, not detail, and returns contract terms only | A new PM reactivating someone another PM worked with (FR-4.3's core case) only has summary visibility |
| 2B | A worker with any non-cancelled engagement can only be engaged through reactivation | Keeps first-time vs repeat metrics (FR-5.3) accurate |
| 2B | Reactivation replays a concurrent duplicate `Idempotency-Key` from the same PM with 200 | The spec says "idempotent on key"; the reason is double-clicks |
| 2B | `ESIGN_WEBHOOK_SECRET` is a new required setting | HMAC-signs and verifies the e-sign webhook (spec §8.1) |

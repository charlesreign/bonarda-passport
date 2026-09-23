# Bonarda Works Passport — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`

The spec's MVA (§10) is delivered as six sequential plans. Each plan ends with working, tested software and is written in full only when its predecessor is merged, so it can build on the real code rather than on guesses.

| # | Plan | Delivers | Depends on | Status |
|---|---|---|---|---|
| 1 | `2026-09-22-bonarda-01-backend-foundation.md` | Backend scaffold, CI checks, shared kernel (settings, DB, problem+json errors, correlation IDs, audit writer, transactional outbox, relay, idempotent handlers, Arq worker), `identity` module (access/refresh tokens, magic links, staff OIDC with MFA check, role permission matrix, `VisibilityPolicy`, access grants, SCIM revocation) | — | Implemented on `feat/backend-foundation` |
| 2 | `…-02-core-reactivation-loop.md` | `passport` (workers, invitations, skills taxonomy, consents), `engagements` (projects, staffing, prefill, reactivation, first-time path, completion, feedback, e-sign webhook, stuck detector), `integrations` (fake e-sign/payroll, SMTP mailer); FKs from Plan 1 tables to `workers`; visibility sources for engagements | 1 | Not written |
| 3 | `…-03-fairness-engine.md` | `policy_configs` with two-person activation, `standing` (rules engine, skill evidence, append-only standing changes), `roster` (read-model, scoring, first-shot, impression logging) | 2 | Not written |
| 4 | `…-04-governance.md` | Disputes with SLA, standing overrides, concentration rollups and alerts, audit-log API, retention enforcement and anonymization | 3 | Not written |
| 5 | `…-05-frontend.md` | Vite/React app: generated API client, providers, `/passport`, `/console`, `/ops` bundles, i18n (en/fr), size budgets, Playwright + axe | 1–4 (API contract) | Not written |
| 6 | `…-06-demo-and-operations.md` | Docker Compose with Keycloak + Mailpit, real `AuthlibOidcProvider` verification against Keycloak, seed data, Prometheus metrics and custom counters, Locust profile | 1–5 | Not written |

Pre-live gates (spec §10) — SCIM wired to the real IdP, real e-sign/payroll adapters, penetration test, legal sign-offs — are outside these plans.

## Carry-forward from Plan 1 (review findings deferred to later plans)

Each item below must become a named task with a test in the plan listed.

| Plan | Item |
|---|---|
| 2 | Add FKs from `user_accounts.worker_id` and `access_grants.scoped_worker_id` to `workers.id`; validate `scoped_worker_id` on grant creation. |
| 2 | `AccessRevoked` handler ends the user's `project_staff` rows. |
| 2 | Pick one role authority: SCIM `roles` vs OIDC `groups` currently both set `role`; reject `worker` over SCIM. Consider revoking sessions on login-time demotion. |
| 2 | SCIM `remove` operations are silently ignored — answer 400 for unsupported ops. |
| 2 | Magic-link `verify()` should re-check `role is WORKER`; send magic-link mail off the request path (timing side channel once SMTP is real). |
| 3 (before any body-addressed worker route) | `unguarded_worker_routes` only checks path/query `worker_id`; extend the visibility guard check to request bodies (`POST /reactivations`). |
| 4 | Grant revocation takes no `reason`; logout audit uses `actor=None` though the user is known; move the SSO-login audit from the router into `OidcLoginService`. |
| 6 | Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` so per-IP magic-link limits see real client IPs. |
| 6 | Wire a real mailer (SMTP/Mailpit) — `create_app` refuses ConsoleMailer outside dev/test. Verify `AuthlibOidcProvider` against Keycloak; map IdP/network failures to `oidc_error`. |
| 6 | Outbox relay polish: wait on `stop` as well as `wake` during backoff (shutdown can block ≤30 s); close the connection if `add_listener` fails; add a connect timeout; one permanently failing event holds the relay in 30 s backoff — consider per-row backoff. |
| 6 | Add metrics `outbox_lag_seconds`, `dead_letter_total` and alerts (spec §8.3). |
| any | Async tests: never write `session.expire_all()` + `session.get()` (raises MissingGreenlet) — use `await session.refresh(obj)`. |
| any | FastAPI is pinned to 0.115.0 because `get_session` relies on yield-dependency teardown running before the response is sent; re-verify before upgrading. |

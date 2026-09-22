# Bonarda Works Passport — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`

The spec's MVA (§10) is delivered as six sequential plans. Each plan ends with working, tested software and is written in full only when its predecessor is merged, so it can build on the real code rather than on guesses.

| # | Plan | Delivers | Depends on | Status |
|---|---|---|---|---|
| 1 | `2026-09-22-bonarda-01-backend-foundation.md` | Backend scaffold, CI checks, shared kernel (settings, DB, problem+json errors, correlation IDs, audit writer, transactional outbox, relay, idempotent handlers, Arq worker), `identity` module (access/refresh tokens, magic links, staff OIDC with MFA check, role permission matrix, `VisibilityPolicy`, access grants, SCIM revocation) | — | Written |
| 2 | `…-02-core-reactivation-loop.md` | `passport` (workers, invitations, skills taxonomy, consents), `engagements` (projects, staffing, prefill, reactivation, first-time path, completion, feedback, e-sign webhook, stuck detector), `integrations` (fake e-sign/payroll, SMTP mailer); FKs from Plan 1 tables to `workers`; visibility sources for engagements | 1 | Not written |
| 3 | `…-03-fairness-engine.md` | `policy_configs` with two-person activation, `standing` (rules engine, skill evidence, append-only standing changes), `roster` (read-model, scoring, first-shot, impression logging) | 2 | Not written |
| 4 | `…-04-governance.md` | Disputes with SLA, standing overrides, concentration rollups and alerts, audit-log API, retention enforcement and anonymization | 3 | Not written |
| 5 | `…-05-frontend.md` | Vite/React app: generated API client, providers, `/passport`, `/console`, `/ops` bundles, i18n (en/fr), size budgets, Playwright + axe | 1–4 (API contract) | Not written |
| 6 | `…-06-demo-and-operations.md` | Docker Compose with Keycloak + Mailpit, real `AuthlibOidcProvider` verification against Keycloak, seed data, Prometheus metrics and custom counters, Locust profile | 1–5 | Not written |

Pre-live gates (spec §10) — SCIM wired to the real IdP, real e-sign/payroll adapters, penetration test, legal sign-offs — are outside these plans.

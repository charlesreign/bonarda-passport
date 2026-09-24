# Bonarda Works Passport — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md`

The spec's MVA (§10) is delivered as six sequential plans. Each plan ends with working, tested software and is written in full only when its predecessor is merged, so it can build on the real code rather than on guesses.

| # | Plan | Delivers | Depends on | Status |
|---|---|---|---|---|
| 1 | `2026-09-22-bonarda-01-backend-foundation.md` | Backend scaffold, CI checks, shared kernel (settings, DB, problem+json errors, correlation IDs, audit writer, transactional outbox, relay, idempotent handlers, Arq worker), `identity` module (access/refresh tokens, magic links, staff OIDC with MFA check, role permission matrix, `VisibilityPolicy`, access grants, SCIM revocation) | — | Implemented on `feat/backend-foundation` |
| 2A | `2026-09-23-bonarda-02a-worker-passport.md` | `passport` (workers, skills taxonomy and claims, profile views, onboarding, consents, PM invitations), SMTP mailer, sign-in mail sent by the worker, per-account locale, Plan 1 identity carry-forward fixes | 1 | Implemented on `feat/worker-passport` |
| 2B | `2026-09-24-bonarda-02b-engagements.md` | `engagements` (projects, staffing, first-time engagements, reactivation prefill and create, contracts via fake e-sign, e-sign webhook, payroll signal, completion, feedback, stuck detector), e-sign/payroll adapters, PM visibility sources, `AccessRevoked` → end `project_staff` | 2A | Written |
| 3A | `2026-09-25-bonarda-03a-standing.md` | governance policies (versioned, two-person activation), standing (rules engine, append-only standing changes, skill evidence and verification, re-evaluation on activation and nightly, explanation API) | 2B | Implemented on `feat/standing` |
| 3B | `2026-09-26-bonarda-03b-roster.md` | roster (read-model, scoring, candidates, first-shot, impression logging, first-shot visibility source) | 3A | Implemented on `feat/roster` |
| 4 | `…-04-governance.md` | Disputes with SLA, standing overrides, concentration rollups and alerts, audit-log API, retention enforcement and anonymization | 3B | Not written |
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
| 4 | Audit that `full_name` changed (`worker.renamed`, recording only that the name changed, never the name: audit_log is append-only and survives erasure, spec §6.3) before contracts print it; don't emit `WorkerUpdated` for no-op PATCHes. |
| 5 | Type `locale` response fields as the `Locale` enum (`MeResponse`, `AccountContact`, `WorkerSelf`) for the generated client. |
| any | Visibility guard compares Python field names only: aliases (`Field(alias="worker_id")`), untyped `dict` bodies and unresolved forward references are not detected. |
| 6 | Fake e-sign never signs by itself; for the demo add auto-sign after a delay (or a dev-only sign endpoint) so the loop runs without a provider. |
| 4 | Worker and PM notifications: "engagement confirmed" to the worker on activation and "feedback due" to the PM on completion (spec §7.7 `notify_worker`, `notify_feedback_due`). |
| 4 | Close a project (`status=closed`); no endpoint yet, so every project stays active. |
| 4 | Closing a project must end its open `project_staff` rows. Staff rows on a closed project otherwise keep granting worker visibility. |
| any | Finance has `engagement:read_billing` but no billing read endpoint yet. |
| any | `sync_worker_status` counts active engagements and then writes the worker row without a lock. A concurrent cancel and activate can leave the worker dormant even though it has an active engagement. |
| 5 | Keyset pagination for `GET /projects` and `GET /workers/{id}/engagements` (spec §7.2); no endpoint paginates yet. |
| 4 | An anonymized worker stays DETAIL-visible to PMs through past engagements; decide what a PM may still see at anonymization. |
| pre-live (real adapters) | Adapter call timeouts; the engagement row lock is held across the external e-sign/payroll call. |
| 4 | `send_contract` retries into dead-letter when the worker account is gone; cancel the engagement instead. |
| any | Reactivation replay ignores body differences (same key, different terms returns the original); consider 422 on mismatch. |
| 4 | A role change at OIDC login ends staffing and revokes sessions but, unlike SCIM `_revoke`, does not close open access grants or write an `access.revoked` audit row (FR-9.5). A grant only acts for the PM role, but an unexpired one revives if the IdP makes the user a PM again. Reuse SCIM's revocation path from the OIDC reconcile. |
| any | Payroll-signal recovery measures its grace period from `billable_start_at`, not from activation. An engagement signed early is activated by the hourly job up to ~1 h after midnight UTC, so the next 15-min run can re-emit `EngagementActivated` while the original is still in the outbox: harmless (the handler is idempotent) but it writes a spurious `engagement.payroll_signal_retried` audit row and warning. Key recovery off the activation time. |
| 4 | Concentration and retention policy kinds have no rules schema yet; proposing one answers 400 `policy_kind_not_supported`. |
| 4 | An upheld dispute must set `feedback.excluded_from_standing` and recalculate the worker (spec §7.7 `DisputeResolved`). |
| 4 | Notify the worker when their standing changes (spec §7.7 `notify_worker` on `StandingChanged`). |
| 4 | Standing overrides (`POST /standing-overrides`) write `standing_changes` with `actor_id` and `override_reason`; the table already has both columns. |
| any | `recalculate_all` re-evaluates every worker in one transaction; batch it if the pool grows well past the pilot's 5,000 profiles. The run also holds a `FOR NO KEY UPDATE` lock on every pool worker until it commits, so a tiering activation during working hours delays worker profile edits, status changes and feedback recalculations for the length of the run; batch commits per group of workers (recalculate is idempotent). |
| any | Skill verification never reverses. Raising the policy threshold does not un-verify skills already verified. |
| any | Skill verification and tier recalculation each take locks in a fixed order, and future code that touches them must keep it: workers are locked `FOR NO KEY UPDATE`, in id order; skill claims are locked `FOR UPDATE`, sorted by skill id. |
| 4 | Add DB invariants for policies: `status='active'` ⇒ `activated_at IS NOT NULL`. Also make proposed policies immutable at the DB level (a trigger or role grants), because today only the application prevents editing `rules`/`created_by_id`. |
| any | The nightly roster rebuild commits in batches of 100 workers, so a rebuild that fails midway leaves earlier batches refreshed. That is harmless; the next run repairs the rest. |
| 4 | First-shot review outcomes have no transition rules. For example, `engaged` → `passed` → `shortlisted` is allowed, and moving a worker out of `engaged` makes them eligible for the panel again. The audit row records the previous outcome. Decide the rules alongside deriving `engaged` from real engagements, before `first_shot_engaged` rollups; closed projects' panels must also be skipped. |
| 4 | Candidates can be searched for a closed project, because nothing checks the project's status. |
| any | Candidate scoring and first-shot selection score the whole eligible pool in Python per request. That is fine at the pilot's 5,000 profiles. Push scoring into SQL, or cache ranked pools per project, if the pool grows well beyond that. |
| 5 | The SPA renders the first-shot panel in the same page layout as candidates, and no toggle can hide it (spec §7.8 `useFirstShot`). |
| 4 | A first-shot `engaged` outcome is recorded by the PM; it is not derived from an actual engagement on the project. Consider setting it automatically when the PM engages that worker on the project. |
| 4 | Concentration rollups (`first_shot_shown`, `first_shot_engaged`) read `first_shot_reviews`. |
| any | The lock-order row gains roster refreshes. They are serialized per worker with a transaction-level advisory lock (`pg_advisory_xact_lock`), taken before any other lock in the refresh. |
| any | The candidate cursor has no `policy_version`, so a matching-policy activation mid-walk can skip or repeat candidates. Add the version and reject a mismatch. |
| any | PM visibility calls `list_staffed_by` once per source; share the lookup. |

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
| 2B | Reactivation prefill needs summary visibility, not detail, and returns contract terms only (scope; no access notes) | A new PM reactivating someone another PM worked with (FR-4.3's core case) only has summary visibility |
| 2B | A worker with any non-cancelled engagement can only be engaged through reactivation (superseded in 3A: only signed or later engagements count as history) | Keeps first-time vs repeat metrics (FR-5.3) accurate |
| 2B | Reactivation replays a concurrent duplicate `Idempotency-Key` from the same PM with 200 | The spec says "idempotent on key"; the reason is double-clicks |
| 2B | `ESIGN_WEBHOOK_SECRET` is a new required setting | HMAC-signs and verifies the e-sign webhook (spec §8.1) |
| 2B | Any staffed PM can edit a project's staff list (spec: people_ops or the owning PM) | Projects record only `created_by_id` (the creator, possibly people_ops), not an owning PM; every staffed PM is treated as an owner. Revisit if staffing needs tighter control |
| 3A | The policy activation path is `POST /policies/{kind}/versions/{v}/activate`, not `:activate` | The same plain-REST convention as Plan 2B |
| 3A | `skill_evidence` is keyed by `(worker_id, skill_id, reviewer_id)`, not `skill_claim_id` | A self-reported claim can be deleted and re-added; evidence must neither block that nor be lost |
| 3A | Standing is also re-evaluated nightly at 03:00 UTC | Tiers must fall when feedback ages out of the window, and no event fires for that |
| 3A | `standing_changes.actor_id` has no `ON DELETE SET NULL` | A cascading update would hit the append-only trigger; staff accounts are revoked, never deleted |
| 3A | `GET /workers/{id}/standing` (detail visibility) exists alongside `GET /workers/me/standing` | Spec §7.1 gives detail viewers standing factors |
| 3A | Reactivation does not re-check profile gaps (location, languages, skills); first-time engagement does | FR-4.3's fast path for returning workers |
| 3A | Reactivation prefill uses the same definition of past work as reactivation (signed, active or completed engagements); a worker whose only engagement is unsigned gets 404 no_prior_engagement from prefill | Prefill and reactivation must agree; before, prefill returned terms that reactivation then refused |
| 3B | `roster_profiles.last_engaged_on` is a date (the latest engagement start), not `last_engaged_at` | Engagements carry start dates, not start times |
| 3B | Roster status, tier and availability columns are plain strings | The roster is a projection and does not share passport's DB enum types |
| 3B | "Last 12 months" means the last 365 days of engagement start dates | Simple, and stable across month lengths |
| 3B | Candidates are paginated with an opaque cursor over the computed score order | Scores are computed per request; the cursor keeps keyset semantics over them |
| 3B | The first-shot panel leaves out workers already `passed` or `engaged` for the project | The panel keeps surfacing new people instead of re-showing decided ones |
| 3B | Candidates and the first-shot panel include only `profile_complete` workers | An invited worker cannot yet be engaged (FR-5.1) |
| 3B | `last_12m` and `last_engaged_on` count only engagements whose start date has passed. Future signed engagements count in `total` only | Roster counters reflect work actually underway or done, not scheduled future starts |
| 3B | Spec §7.7 lists `EngagementCreated → roster.refresh_worker`, but the roster subscribes `ContractSigned`, `EngagementCompleted` and `EngagementCancelled` | Only signed-or-later engagements count toward activity |

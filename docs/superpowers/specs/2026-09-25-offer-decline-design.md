# Offer Decline — Design

**Date:** 2026-09-25
**Parent spec:** `2026-09-22-bonarda-system-design-v2.md`
**Branch:** `feat/offer-decline`

## 1. Goal

When a PM onboards a freelancer onto a project (first-time or reactivation engagement), the freelancer can decline the offer from inside the app, giving a reason. The PMs on the project are told, People Ops can see a worker's declines, and a decline never affects standing or roster ranking.

### Decisions taken during design

| Question | Decision |
|---|---|
| Offer step before the contract, or decline alongside the existing flow? | Alongside. The contract is still sent as soon as the PM confirms (FR-4.3 speed is unchanged); the worker can decline in the app while the contract is unsigned. |
| Does declining have consequences? | Recorded, not scored. Declines are stored and counted; no standing rule or roster score reads them. `TieringRules` forbids extra fields, so scoring them would need a deliberate code change. |
| Who sees declines? | The worker (own), People Ops and admin (all), PMs staffed on the offering project (that engagement). Other PMs never see a declined engagement, and the roster never shows a count. |
| How is a decline modelled? | The engagement ends `cancelled`, as an e-sign decline does today, with a recorded `cancel_cause`. No new status. |

### Out of scope (roadmap carry-forwards)

- A PM withdrawing an offer (`pm_withdrew` cause).
- An organisation-wide decline rollup on the governance overview.
- An offer-expiry step (unanswered offers lapsing).
- A retention cutoff for decline notes: only erasure clears them for now.

## 2. Current behaviour

A PM creates an engagement (`POST /workers/{id}/engagements` or `POST /reactivations`). It is recorded as `pending_signature`; the outbox sends the contract and moves it to `awaiting_signature`. If the worker declines the envelope at the e-sign provider, the webhook (`ContractService._declined`) sets `cancelled` and emits `EngagementCancelled`. No reason is recorded, nobody is notified, and there is no in-app decline. Standing ignores cancelled engagements (`HISTORY_STATUSES` excludes them); roster only refreshes its read model on `EngagementCancelled`.

## 3. Data model

New migration `0016_engagement_decline`, after `0015_concentration`. Nullable columns on `engagements`:

| Column | Type | Meaning |
|---|---|---|
| `cancel_cause` | enum `cancelcause` | `worker_declined`, `esign_declined` or `worker_account_missing` |
| `declined_at` | timestamptz | When the worker declined (either route) |
| `decline_reason` | enum `declinereason` | `rate`, `dates`, `scope`, `availability` or `other` |
| `decline_note` | varchar(500) | Optional free text from the worker |
| `void_requested_at` | timestamptz | When the e-sign envelope was voided after a decline |

`cancel_cause` and `decline_reason` are native Postgres enums (`pg_enum`, like every other status column), backed by `StrEnum`s in `engagements/enums.py` (`CancelCause`, `DeclineReason`). The row invariants are CHECK constraints:

- `(status = 'cancelled') = (cancel_cause IS NOT NULL)`
- `COALESCE(cancel_cause IN ('worker_declined','esign_declined'), false) = (declined_at IS NOT NULL)`
- `decline_reason IS NULL OR cancel_cause = 'worker_declined'`
- `decline_note IS NULL OR decline_reason IS NOT NULL`
- `cancel_cause IS DISTINCT FROM 'worker_declined' OR decline_reason IS NOT NULL`

**Backfill:** before adding the constraints, existing `cancelled` rows take their cause from the audit log — `engagement.contract_declined` → `esign_declined` with `declined_at` = the audit row's `occurred_at`; `engagement.cancelled` with `reason = worker_account_missing` → `worker_account_missing`. A cancelled row matching neither (none are expected) gets `worker_account_missing` and the migration logs its id. The downgrade drops the constraints and columns.

Every path that sets `status = cancelled` goes through one helper, `cancel()` in `engagements/cancellation.py`, which sets `cancel_cause` (and `declined_at` for a decline), writes the audit row and emits the events: `send_contract` (account missing), `ContractService._declined` (e-sign), and the new decline service.

## 4. Declining

### Endpoint

`POST /api/v1/workers/me/engagements/{engagement_id}/decline`

- Body `DeclineRequest`: `reason: DeclineReason`, `note: str | None` (1–500 chars after stripping; blank becomes `null`). `extra="forbid"`.
- Permission: new `engagement:decline_own`, granted to `worker` only; `docs/permissions.md` is regenerated.
- The engagement must belong to the caller's worker profile; otherwise 404 `engagement_not_found` (no existence leak).
- Response 200 `EngagementRead` (with the `decline` block, §5).

### Service: `DeclineService.decline(actor, worker_id, engagement_id, data)` in `engagements/declines.py`

Locks the row (`get_for_update`), then:

| Current state | Result |
|---|---|
| `pending_signature` | Declined; no envelope exists and `send_contract` already skips non-sendable rows |
| `awaiting_signature` | Declined; `ContractVoidRequested` emitted |
| `cancelled` with `cancel_cause = worker_declined` | 200 with the current record (replay; the stored reason is kept) |
| anything else | 409 `engagement_not_declinable` |

On decline, in one transaction: `status = cancelled`, `cancel_cause = worker_declined`, `declined_at = now`, reason and note set, `stuck_flagged_at = None`; audit `engagement.declined` with the worker as actor and `after = {"reason": ...}` (the note is not copied into the audit log, so erasure only clears one place); events `EngagementCancelled(cause=worker_declined)`, `EngagementDeclined(aggregate_id, worker_id, project_id, cause)` and, if an envelope was sent, `ContractVoidRequested(aggregate_id, envelope_id)`.

`EngagementCancelled` gains a `cause: CancelCause` field; existing consumers (roster refresh, worker-status sync) ignore it.

### Voiding the envelope

`EsignAdapter` gains `async def void(self, envelope_id: str) -> None`, idempotent per envelope. `FakeEsignAdapter` records voided ids. The `ContractVoidRequested` outbox handler calls it and sets `void_requested_at`; a failure retries through the outbox, so a provider outage never blocks the decline.

### E-sign decline

`ContractService._declined` additionally sets `cancel_cause = esign_declined` and `declined_at`, and emits `EngagementDeclined(cause=esign_declined)`, so PMs are told about provider-side declines too.

### Races

Both the decline and the e-sign webhook lock the engagement row, so the first to commit wins. Signed first → the decline gets 409. Declined first → the `signed` webhook finds `cancelled`, changes nothing, and records an `engagement.signed_after_decline` audit row plus a warning log, so People Ops and operators can see a stray signature. The demo sign route (`app/demo.py`) behaves the same way.

### Erasure

Anonymising a worker sets `decline_note = NULL` on their engagements, in a new `engagements.scrub_decline_notes` handler for `passport.worker_anonymized` (audit `engagement.decline_note_removed`). Reason and cause are kept; they are not personal free text.

## 5. Visibility

`EngagementRead` gains `decline: DeclineRead | None` — `{cause, declined_at, reason, note}` — set only for declined engagements the viewer may see. `cancel_cause` is not exposed otherwise.

One helper, `decline_visible_to(actor, level, engagement, staffed_project_ids) -> bool`, decides:

| Viewer | Declined engagements |
|---|---|
| The worker (`Visibility.SELF`) | Shown in full |
| People Ops, admin | Shown in full |
| PM staffed on the engagement's project | Shown in full |
| Any other PM | Row omitted |

`GET /workers/{worker_id}/engagements` resolves the actor and the PM's staffed project ids once per request and filters with the helper. Both decline causes are filtered; `worker_account_missing` cancellations are unchanged. Project-scoped reads already require staffing, so they only add the `decline` block.

Roster, candidates, first-shot and standing are unchanged. A test pins this (§8).

## 6. Notifications

`notify_offer_declined(session, mailer, engagement_id)` handles `EngagementDeclined`: it mails every active PM staffed on the project (as `notify_feedback_due` does) with the worker's name, the project, and — for `worker_declined` — the reason and note, localised through `core/i18n` (new `offer_declined.*` keys in en and fr). No recipients → returns 0; the event never dead-letters.

## 7. Frontend

- **Worker (`Passport.tsx`, `ContractToSign`):** a "Decline offer" button beside the sign button opens an inline form: reason select (required), note (optional, 500-char counter), and the line "Your reason goes to this project's managers and People Ops. Declining does not affect your standing." On success the engagements query is invalidated and the card shows "Declined". A 409 shows "This offer can no longer be declined".
- **People Ops (`WorkerPanel.tsx`):** a "Declined offers" row with the count and a list (project, date, cause, reason; note on expand), from the existing engagements query.
- **PM (`ProjectPage.tsx`):** a declined engagement shows "Declined" with the reason and note.
- All strings go through i18n (en and fr). `openapi.json` and `api-schema.d.ts` are regenerated with `export_openapi`.

## 8. Testing

Backend:

- **Migration** (`tests/integration/test_engagement_decline_schema.py`): each CHECK constraint rejects its invalid shape; the backfill maps both audit patterns; upgrade/downgrade round-trip.
- **Endpoint** (`tests/api/engagements/test_decline.py`): decline from `pending_signature` and `awaiting_signature` (the latter emits `ContractVoidRequested`); replay returns 200; 409 once signed, active, completed or cancelled for another cause; 404 for another worker's engagement; 403 for staff callers; note length and reason validation; audit row has the worker as actor and no note.
- **Visibility** (`tests/api/engagements/test_decline_visibility.py`): worker, People Ops, admin, staffed PM, unstaffed PM with DETAIL visibility (row omitted) — for both decline causes; `worker_account_missing` rows unchanged.
- **Races and webhooks:** `signed` after decline is ignored and logged; e-sign `declined` sets cause and `declined_at` and emits `EngagementDeclined`.
- **Handlers:** `notify_offer_declined` mails each active staffed PM in their locale and returns 0 with no recipients; the void handler and `FakeEsignAdapter.void` are idempotent.
- **Neutrality:** a declined engagement changes neither `standing_records`/`evaluate` nor the candidate score.
- **Erasure:** anonymisation clears `decline_note`.
- The i18n parity test covers the new keys; the visibility-guard and module-boundary tests pass unchanged.

Frontend: typecheck, lint, size budgets and `npm run check:api` pass. No Playwright suite exists yet (roadmap carry-forward), so the three views are checked by hand against the demo stack, including the PM mail in Mailpit.

## 9. Deviations from the parent spec

| Deviation | Reason |
|---|---|
| A worker-facing engagement mutation (`POST /workers/me/engagements/{id}/decline`) and permission `engagement:decline_own` | The parent spec has no worker action on engagements; declining needs one |
| `engagements` gains `cancel_cause` and decline columns (parent spec §6.1) | Records why an engagement was cancelled |

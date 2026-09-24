# Bonarda Works — Freelancer Passport & Reactivation Platform
### Product Requirements Document

**Prepared by:** Product Management
**Status:** Draft for stakeholder review
**Scope:** Onboarding and re-engagement of repeat contractors and freelancers

---

## 1. Executive summary

Bonarda Works delivers projects across Africa and Europe through a blended workforce of employees, contractors and freelancers. As the company scales, one failure mode has become costly and visible: **every engagement resets to zero**, even for people Bonarda already knows and trusts. A freelancer who has delivered three successful projects goes through the same onboarding as a stranger on their fourth.

This document defines requirements for a system that gives contractors and freelancers a **persistent, portable record** — a "passport" — carrying verified skills, engagement history and standing forward across projects, paired with a **PM-facing console** that lets project managers reactivate known talent in a fraction of the time of standard onboarding, without that speed quietly narrowing who gets opportunities.

The system is scoped narrowly by design: it does not attempt to solve sourcing, payroll, or learning and development. It solves the handoff between "we've worked with this person before" and "they're active on a new project."

---

## 2. Problem statement

| # | Observation | Impact |
|---|---|---|
| 1 | Contractors and freelancers are re-onboarded from scratch on every engagement, regardless of prior history with Bonarda | PM time wasted re-collecting known information; slower time-to-billing |
| 2 | A freelancer's track record lives in one PM's memory or inbox, not in any shared system | Good freelancers get under-utilized simply because the next PM doesn't know their history |
| 3 | Freelancers have no visibility into their own standing with Bonarda | Freelancers can't tell if the relationship is growing, so they have no reason to prioritize Bonarda over other clients |
| 4 | Faster onboarding for known people, left unchecked, tends to concentrate work on an ever-smaller "inner circle" | Undermines the equitable-experience goal even while appearing to improve efficiency |

---

## 3. Objectives and success metrics

| Objective | Metric | Target (12 months post-launch) |
|---|---|---|
| Reduce re-onboarding time for known freelancers | Median days from "confirmed for project" to "billable start," repeat engagements | ≤ 1.5 days (from a baseline that will be measured pre-launch) |
| Reduce PM administrative burden | PM hours spent per reactivation vs. first-time onboarding | ≥ 60% reduction |
| Improve freelancer retention | % of freelancers with 2+ engagements who re-engage within 12 months | +20 percentage points vs. baseline |
| Prevent opportunity concentration | Share of engagements going to freelancers with 3+ prior engagements | Tracked monthly; flagged if it exceeds an agreed ceiling (e.g. 65%) rather than left to grow unchecked |
| Freelancer-perceived fairness | Survey: "I can see where I stand with Bonarda" (agree/strongly agree) | ≥ 75% |

---

## 4. Personas and stakeholders

| Persona | Description | Primary need |
|---|---|---|
| **Kofi — repeat freelancer** | Engaged 3–5x/year, remote across countries, invoice-based | Not re-proving himself every time; visibility into his own standing |
| **Grace — first-time / underused freelancer** | Qualified, verified, but rarely selected | A real chance to be considered, not just filtered out by "known" defaults |
| **Ama — project manager** | Staffs 2–4 concurrent projects, limited admin bandwidth | Fast, low-risk reactivation of trusted people; visibility into who else is qualified |
| **HR / People Ops** | Owns compliance, contracts, equitable-experience mandate | Auditable records; concentration metrics; dispute handling |
| **Finance / Payments** | Owns contractor payments | Reliable link between engagement records and payment triggers (integration, not rebuild) |
| **Engineering / IT** | Owns integrations and data | Clear boundaries with identity, e-signature, and payroll systems |

---

## 5. Scope

**In scope**
- Persistent worker profile (skills, verified history, standing) for contractors and freelancers
- PM console for searching, viewing and reactivating known talent
- A parallel, deliberately surfaced list of qualified-but-underused talent
- Freelancer-facing passport view of their own record
- Structured, low-bias feedback capture at the end of each engagement
- Concentration/equity monitoring (internal metric, not freelancer-facing at launch)
- Worker-facing data visibility and dispute mechanism

**Out of scope (v1)**
- Talent sourcing / discovery of entirely new candidates
- Full applicant tracking or recruitment workflow
- Payroll processing (integrates with existing payments system, does not replace it)
- Contract generation and e-signature engine (integrates with existing/selected provider)
- Learning & development content or course delivery
- Full offboarding workflow beyond passing engagement data into the passport

**Explicitly deferred, flagged for later phases**
- Extending the passport model to full-time employees
- Cross-border data residency architecture beyond what's needed for pilot markets

---

## 6. Functional requirements

Requirements use MoSCoW priority: **M**ust, **S**hould, **C**ould, **W**on't (this phase).

### 6.1 Worker profile & passport

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-1.1 | System shall maintain one persistent profile per contractor/freelancer, keyed to a unique worker ID | M | Survives across engagements and PM turnover |
| FR-1.2 | Profile shall store: contact details, base location, skills, engagement history, standing/tier, verified credentials | M | |
| FR-1.3 | Worker shall be able to view their own profile, including standing and the specific signals behind it | M | Directly supports transparency/dispute requirement |
| FR-1.4 | Worker shall be able to flag a specific record (rating, engagement note) as disputed, with a reason | M | Routes to HR/People Ops queue |
| FR-1.5 | Worker shall be able to update self-reported fields (languages, availability, certifications) | S | Subject to re-verification where relevant |
| FR-1.6 | System shall display engagement history as discrete entries: project, dates, location/mode, outcome rating | M | |
| FR-1.7 | System shall support worker-initiated data export of their own profile | C | Supports portability and trust |

### 6.2 Skills verification

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-2.1 | System shall record skill claims with a verification status: unverified / self-reported / Bonarda-verified | M | Never silently present unverified as verified |
| FR-2.2 | A skill shall only move to "Bonarda-verified" after evidence from more than one engagement or reviewer | M | Prevents one PM's opinion from creating a badge |
| FR-2.3 | System shall support structured, behavior-specific end-of-engagement questions (e.g. "delivered on agreed dates: yes/no") rather than free-text star ratings only | M | Reduces subjective bias in the record |
| FR-2.4 | System shall allow optional free-text feedback in addition to structured fields, visible to the worker | S | |
| FR-2.5 | System shall support external credential input (certifications, LinkedIn) to pre-fill claims for first-time workers | C | Reduces cold-start gap |

### 6.3 Standing / tiering

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-3.1 | System shall calculate a standing/tier from a defined, documented rule set (not ad hoc PM judgment) | M | Rules must be inspectable by HR/People Ops |
| FR-3.2 | Standing calculation shall require a minimum number of engagements and reviewers before reaching "Trusted" tiers | M | |
| FR-3.3 | System shall log every change to a worker's standing with the contributing factors | M | Supports audit and dispute resolution |
| FR-3.4 | Standing shall never be the sole basis for excluding a worker from consideration | M | Enforced in matching/surfacing logic, FR-4.x |

### 6.4 PM console — reactivation

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-4.1 | PM shall be able to search/filter the roster by skill, availability, location, and prior engagement | M | |
| FR-4.2 | PM shall see, for any known worker, engagement history, verified skills, standing, and last-reactivation time-to-start | M | |
| FR-4.3 | PM shall be able to initiate reactivation via a guided flow: confirm scope & rate → carry forward contract/access details → send for e-signature | M | Contract/e-sign is an integration, not built here |
| FR-4.4 | System shall pre-fill contract and access fields from the most recent equivalent engagement, all fields editable | M | |
| FR-4.5 | Reactivated engagement shall appear on the worker's own passport view without manual sync | M | Same underlying record, not a copy |
| FR-4.6 | Console shall present a "ready for a first shot" panel of qualified, underused workers alongside the known-roster results, not hidden behind an extra filter | M | Structural equity control, not optional |
| FR-4.7 | System shall log, per project, whether a first-shot candidate was reviewed and the outcome | S | Enables downstream reporting, not a blocker to staffing |
| FR-4.8 | Console shall display a rolling concentration metric (% of engagements going to repeat vs. new/underused workers) | S | Visible to PM leadership and People Ops, not necessarily every PM |

### 6.5 Onboarding path (first-time and repeat)

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-5.1 | System shall support a standard onboarding path for first-time workers, distinct from reactivation | M | |
| FR-5.2 | Standard onboarding shall pre-fill from external/self-reported sources where possible to reduce redundant data entry | S | |
| FR-5.3 | System shall track and display time-to-billable-start for both paths, to monitor whether the gap between them widens over time | S | Ties to FR fairness objective |

### 6.6 Matching support

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-6.1 | System shall recommend candidates for a role based on verified skills and availability, not solely on past selection frequency | M | Prevents recommendation loop reinforcing incumbents |
| FR-6.2 | Recommendation logic shall be documented and reviewable by People Ops | M | |

### 6.7 Reporting & governance

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-7.1 | System shall provide People Ops a dashboard of concentration metrics, dispute volume, and tier distribution | M | |
| FR-7.2 | System shall alert People Ops if repeat-engagement concentration exceeds an agreed threshold | S | |
| FR-7.3 | System shall maintain a full audit trail of standing changes, dispute resolutions, and reactivation actions | M | Compliance and trust requirement |

### 6.8 Integrations

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-8.1 | System shall integrate with the identity/SSO provider for authentication | M | |
| FR-8.2 | System shall integrate with the e-signature provider to send contracts generated from reactivation flow | M | |
| FR-8.3 | System shall integrate with the payments/payroll system to signal an active engagement, without duplicating payment logic | M | |
| FR-8.4 | System shall expose an API for future integration with a sourcing/ATS tool, without requiring rework of the core data model | C | |

### 6.9 User management & authentication

Internal staff and workers have fundamentally different relationships to Bonarda — the former have corporate identities already, the latter mostly don't. This section treats them as two distinct identity populations rather than assuming one SSO integration covers both.

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| FR-9.1 | Internal staff (PM, People Ops, Finance, Admin) shall authenticate via Bonarda's existing corporate SSO/identity provider | M | No separate credential store for internal users |
| FR-9.2 | Contractors and freelancers shall have a distinct, lightweight identity path (e.g. email verification or magic link), since most are outside the corporate directory | M | This is the account the passport is built on — it must not depend on corporate SSO |
| FR-9.3 | System shall define a fixed role set — PM, People Ops, Finance, Freelancer/Contractor, Admin — each with an explicit, documented permission matrix | M | Roles are not to be inferred from job title; permissions are explicit and reviewable |
| FR-9.4 | A PM's default visibility shall be limited to workers relevant to their active/eligible projects, not the full worker roster | M | Restates NFR-3.2 as an enforceable functional rule, not just a stated principle |
| FR-9.5 | People Ops shall be able to grant a PM temporary, scoped visibility into a worker outside their usual project set, with the grant, grantor, reason, and expiry logged | M | Supports legitimate cross-team staffing needs without permanent over-access |
| FR-9.6 | Worker (freelancer/contractor) accounts shall persist across engagements rather than being created and deleted per project | M | Directly required by the passport concept — an account that resets defeats the purpose |
| FR-9.7 | A worker account with no active engagement shall enter a defined "dormant" state — viewable by the worker, not deleted — with a documented reactivation path | M | Distinguishes "not currently engaged" from "removed" |
| FR-9.8 | System shall support account recovery for workers without relying on corporate IT helpdesk processes built for staff | M | Freelancers won't have access to internal support channels |
| FR-9.9 | System shall require multi-factor authentication for internal roles with access to more than one worker's data | M | Proportionate: freelancers viewing only their own record are lower risk |
| FR-9.10 | System shall offer optional MFA for worker accounts, encouraged but not mandatory at launch | S | Revisit as mandatory once adoption data exists |
| FR-9.11 | System shall enforce session timeout and re-authentication on the PM console after a defined period of inactivity, given the sensitivity of rating and dispute data visible there | M | |
| FR-9.12 | Access revocation for internal staff shall be automatic when their corporate SSO account is deactivated or changes team, without a manual cleanup step | M | Prevents stale access surviving a role change or departure |
| FR-9.13 | Every access grant, role change, and revocation shall be logged with actor, target, reason, and timestamp | M | Feeds the audit trail in FR-7.3 |

---

## 7. Non-functional requirements

### 7.1 Performance
- NFR-1.1 (M): PM console search and profile views shall return results in ≤ 2 seconds at p95 under expected concurrent load.
- NFR-1.2 (M): Reactivation flow (confirm → pre-fill → send) shall complete end-to-end in ≤ 5 seconds of system processing time, excluding external e-signature turnaround.
- NFR-1.3 (S): Passport view shall load in ≤ 2 seconds on a standard mobile connection (3G-equivalent), given usage across varied connectivity in Africa and Europe.

### 7.2 Availability & reliability
- NFR-2.1 (M): Core platform (profile, console, passport) shall target 99.5% uptime during business hours across all served time zones.
- NFR-2.2 (M): No single point of failure in the reactivation flow shall block a worker's existing record from being viewed, even if the reactivation feature itself is degraded.
- NFR-2.3 (S): Scheduled maintenance shall be communicated at least 48 hours in advance and scheduled outside peak PM working hours across served regions.

### 7.3 Security
- NFR-3.1 (M): All data in transit and at rest shall be encrypted (TLS 1.2+, AES-256 at rest).
- NFR-3.2 (M): Access to worker records shall be role-based; PMs see only workers relevant to their active/eligible projects, not the full company roster, unless granted broader access (see FR-9.5).
- NFR-3.3 (M): All administrative actions (standing changes, dispute resolutions, data exports) shall be logged with actor, timestamp, and before/after state.
- NFR-3.4 (M): System shall undergo a security review/penetration test before handling live worker data.
- NFR-3.5 (M): Internal-role access revocation shall complete within 15 minutes of a corporate SSO deactivation or team change event (supports FR-9.12).
- NFR-3.6 (M): MFA shall be enforced at login for any role with access to more than one worker's data; enforcement shall not be bypassable via a "remember this device" setting beyond 30 days.
- NFR-3.7 (S): PM console sessions shall time out after 30 minutes of inactivity; worker passport sessions after 24 hours, reflecting the difference in data sensitivity exposed.
- NFR-3.8 (M): Temporary access grants (FR-9.5) shall auto-expire and shall not require manual revocation to lapse.

### 7.4 Privacy & compliance
- NFR-4.1 (M): System shall comply with applicable data protection law in each operating jurisdiction, including Ghana's Data Protection Act and, for EU-touching data, GDPR.
- NFR-4.2 (M): Workers shall be able to request a copy of, or correction to, their personal data, with a defined response SLA.
- NFR-4.3 (M): Cross-border transfer or reuse of worker data (e.g. for matching across regions) shall require documented legal basis and, where required, worker consent — not assumed by default.
- NFR-4.4 (S): Data retention periods shall be explicitly defined per data category (profile, ratings, disputes) and enforced, not indefinite by default.

### 7.5 Fairness & auditability
*(Treated as non-functional because it's a system-wide quality attribute, not a single feature.)*
- NFR-5.1 (M): Standing/tier calculation logic shall be deterministic, versioned, and reviewable — no undocumented manual overrides without a logged reason.
- NFR-5.2 (M): The system shall not allow "known/fast-track" workflows to structurally hide or deprioritize qualified underused candidates in default views.
- NFR-5.3 (S): Concentration metrics (FR-7.1) shall be computed on a defined cadence (e.g. weekly) without manual intervention, so drift is caught early rather than discovered in hindsight.

### 7.6 Scalability
- NFR-6.1 (M): System shall support at least 5,000 active worker profiles and 500 concurrent PM sessions at launch, with a documented path to 10x without architectural rework.
- NFR-6.2 (S): Data model shall accommodate future extension to full-time employees and additional worker types without a breaking schema change.

### 7.7 Usability & accessibility
- NFR-7.1 (M): PM console and passport view shall meet WCAG 2.1 AA accessibility standards.
- NFR-7.2 (M): Core flows (search, reactivate, view passport) shall be usable without training, validated via usability testing with actual PMs and at least one freelancer cohort before launch.
- NFR-7.3 (S): Passport view shall be usable on low-end Android devices, given the freelancer base's varied device access.

### 7.8 Localization
- NFR-8.1 (M): System shall support English and French at launch, given Bonarda's Africa/Europe footprint; architecture shall not hardcode English-only strings.
- NFR-8.2 (S): Date, currency, and number formats shall adapt to the worker's or PM's locale setting.

### 7.9 Maintainability & extensibility
- NFR-9.1 (M): System shall expose a documented API layer so future modules (sourcing, L&D, offboarding) can integrate without direct database access.
- NFR-9.2 (S): Business rules for tiering and matching shall be configurable by People Ops within defined bounds, without requiring an engineering deployment for routine threshold changes.

### 7.10 Observability
- NFR-10.1 (M): System shall log key events (reactivation started/completed, dispute filed/resolved, standing changed) to support both debugging and the governance dashboard (FR-7.1).
- NFR-10.2 (S): System shall alert engineering on integration failures (e-signature, identity, payments) within 5 minutes of detection.

---

## 8. Assumptions

- Bonarda Works has, or will designate, a People Ops owner responsible for tiering rules, dispute resolution, and concentration monitoring — this system surfaces data but does not replace human judgment on fairness questions.
- Identity/SSO, e-signature, and payments systems either already exist or will be selected independently; this system integrates with them rather than replacing them.
- A baseline measurement of current onboarding time and engagement concentration will be captured pre-launch to validate the targets in Section 3.

## 9. Constraints

- Cross-border data handling must respect the stricter of any two jurisdictions' requirements where a worker or project spans both.
- v1 targets contractors and freelancers only; extending the model to employees is a distinct, later initiative requiring its own requirements pass (different data sensitivity, different legal relationship).

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| "Ready for a first shot" panel is ignored in practice despite being visible | Medium | High — undermines the core equity goal | Track review/outcome rate (FR-4.7); escalate via concentration alerts (NFR-5.3) |
| Structured feedback questions get treated as a checkbox exercise, not honest input | Medium | Medium | Periodic sampling review by People Ops; pair with optional free text |
| Cross-border compliance requirements delay launch | Medium | High | Engage legal early; scope pilot to a single jurisdiction pair if needed |
| PMs route around the system (informal reactivation via email/WhatsApp) | Medium | Medium | Make the in-system path faster than the workaround; track adoption |

## 11. Open questions for stakeholder review

1. Who owns the threshold that triggers a concentration alert (NFR-5.3) — People Ops, PM leadership, or both?
2. Should the freelancer-facing passport show their tier explicitly, or only the underlying signals? (Affects FR-1.3 design, not just copy.)
3. What is the minimum viable jurisdiction scope for pilot — Ghana only, or Ghana + one EU country?
4. Does Bonarda already have an e-signature and identity provider, or is provider selection part of this initiative's critical path?

---

*This document defines requirements for review and refinement with engineering, legal, People Ops, and a sample of PMs and freelancers before committing to a build plan.*

**Bonarda Works: Freelancer Passport**

Bonarda Works staffs projects with freelancers in Ghana and the EU. Today, a freelancer's record resets with every project. Project managers can't easily bring back people they trust, and the same few freelancers win most of the work. The Freelancer Passport keeps one lasting record per freelancer: engagements, feedback, verified skills and a standing tier the freelancer can see and understand.

**What it does**
- **Reactivation in minutes:** a PM finds a past freelancer, the contract terms are prefilled from their last engagement, and one confirmation sends the contract. When the freelancer signs, the engagement goes live.
- **A fair first shot:** every staffing page shows a mandatory panel of qualified freelancers who have had little recent work. Tier never filters them out, and each pass needs a reason.
- **Standing you can explain:** tiers come from versioned rules; any change needs a second People Ops approval. Freelancers see the signals behind their tier and can dispute any record. An upheld dispute removes that feedback from their standing.
- **Governance:** People Ops work a dispute queue with 30-day deadlines, can override a tier (a reason is required), and have a full audit trail. Freelancers and PMs are notified by email in English or French.

**How it's built**
- **Backend:** a FastAPI modular monolith on PostgreSQL. Every change is written together with its audit record and its outgoing event. The events drive recalculations, notifications and the e-signature and payroll integrations.
- **Access and privacy:** one visibility policy decides who can see which freelancer, and free text about freelancers never goes into logs or events.
- **Frontend:** React with a warm, accessible design, checked against WCAG contrast and on mobile.
- **Quality:** 522 automated tests, strict type checking and enforced module boundaries.

**Demo**
`docker compose up --build` starts everything: the app, a background worker, a test mailbox (Mailpit) and seed data (24 freelancers, 3 live projects, an open dispute). One-click demo sign-in covers every role.

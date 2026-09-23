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
    assert (
        await client.post("/api/v1/webhooks/esign", content=body, headers=headers)
    ).status_code == 204
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

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.contracts import activate_due
from app.modules.engagements.enums import CancelCause, DeclineReason, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.payroll import signal_payroll
from app.modules.engagements.stuck import flag_stuck
from app.modules.identity.models import UserAccount
from app.modules.integrations.service import FakeEsignAdapter, FakePayrollAdapter
from app.modules.passport.enums import WorkerStatus
from app.modules.passport.models import Worker
from tests.support import (
    bearer,
    engagement_terms,
    esign_webhook,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]
WEBHOOK = "/api/v1/webhooks/esign"


async def _engage(
    client: AsyncClient, session: AsyncSession, settings: Settings, **overrides: object
) -> tuple[dict[str, Any], Worker, UserAccount]:
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, _ = await make_ready_worker(session, email="kofi@example.com")
    response = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id, **overrides),
        headers=bearer(settings, pm),
    )
    assert response.status_code == 201
    return response.json(), worker, pm


async def _engagement(session: AsyncSession, engagement_id: object) -> Engagement:
    row = await session.get(Engagement, engagement_id)
    assert row is not None
    await session.refresh(row)
    return row


async def _sign(
    client: AsyncClient, settings: Settings, envelope_id: str, event: str = "signed"
) -> int:
    body, headers = esign_webhook(settings, {"envelope_id": envelope_id, "event": event})
    return (await client.post(WEBHOOK, content=body, headers=headers)).status_code


async def test_contract_is_sent_by_the_worker_process(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    created, worker, _ = await _engage(client, session, settings)

    assert esign.sent == {}
    await drain()

    engagement = await _engagement(session, created["id"])
    document = esign.sent[engagement.id]
    assert (document.signer_email, document.signer_name) == ("kofi@example.com", "Kofi Mensah")
    assert document.project_name == "Project Volta"
    assert engagement.status.value == "awaiting_signature"
    assert engagement.esign_envelope_id == f"fake-env-{engagement.id}"
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "engagement.contract_sent" in actions


async def test_signing_on_or_after_the_start_date_activates_and_signals_payroll(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    payroll: FakePayrollAdapter,
) -> None:
    created, worker, _ = await _engage(client, session, settings)
    await drain()
    engagement = await _engagement(session, created["id"])

    assert await _sign(client, settings, engagement.esign_envelope_id or "") == 204
    await drain()

    engagement = await _engagement(session, created["id"])
    assert engagement.status.value == "active"
    assert engagement.billable_start_at is not None
    # Signed on or after the start date: billing starts at the signature.
    assert engagement.billable_start_at == engagement.signed_at
    assert engagement.payroll_signaled_at is not None
    assert list(payroll.activations) == [engagement.id]
    await session.refresh(worker)
    assert worker.status is WorkerStatus.ACTIVE


async def test_replayed_webhook_changes_nothing(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    payroll: FakePayrollAdapter,
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    envelope = (await _engagement(session, created["id"])).esign_envelope_id or ""
    await _sign(client, settings, envelope)
    await drain()

    again = await _sign(client, settings, envelope)
    declined_late = await _sign(client, settings, envelope, event="declined")
    await drain()

    assert (again, declined_late) == (204, 204)
    engagement = await _engagement(session, created["id"])
    assert engagement.status.value == "active"
    signed = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "engagement.contract_signed")
        )
    ).all()
    assert len(signed) == 1
    signaled = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "engagement.payroll_signaled")
        )
    ).all()
    assert len(signaled) == 1
    assert list(payroll.activations) == [engagement.id]


async def test_future_start_is_signed_then_activated_once_by_the_hourly_job(
    client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Drain,
) -> None:
    start = (utcnow() + timedelta(days=10)).date().isoformat()
    created, _, _ = await _engage(client, session, settings, start_date=start)
    await drain()
    await _sign(
        client, settings, (await _engagement(session, created["id"])).esign_envelope_id or ""
    )

    assert (await _engagement(session, created["id"])).status.value == "signed"
    async with sessionmaker() as s, s.begin():
        assert await activate_due(s) == 0
    await session.execute(
        update(Engagement).where(Engagement.id == created["id"]).values(start_date=utcnow().date())
    )
    await session.commit()
    async with sessionmaker() as s, s.begin():
        first = await activate_due(s)
    async with sessionmaker() as s, s.begin():
        second = await activate_due(s)

    assert (first, second) == (1, 0)
    assert (await _engagement(session, created["id"])).status.value == "active"


async def test_declined_contract_cancels_the_engagement(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    envelope = (await _engagement(session, created["id"])).esign_envelope_id or ""

    assert await _sign(client, settings, envelope, event="declined") == 204

    assert (await _engagement(session, created["id"])).status.value == "cancelled"


async def test_bad_signatures_and_unknown_envelopes_are_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    body, headers = esign_webhook(settings, {"envelope_id": "nope", "event": "signed"})

    forged = await client.post(
        WEBHOOK, content=body, headers=headers | {"X-Bonarda-Signature": "sha256=00"}
    )
    unknown = await client.post(WEBHOOK, content=body, headers=headers)
    garbage_body, garbage_headers = esign_webhook(settings, {"event": "signed"})
    garbage = await client.post(WEBHOOK, content=garbage_body, headers=garbage_headers)

    assert (forged.status_code, forged.json()["code"]) == (401, "webhook_signature_invalid")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "envelope_not_found")
    assert (garbage.status_code, garbage.json()["code"]) == (400, "invalid_webhook_payload")


async def test_cancelled_before_dispatch_is_never_sent(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await session.execute(
        update(Engagement)
        .where(Engagement.id == created["id"])
        .values(
            status=EngagementStatus.CANCELLED,
            cancel_cause=CancelCause.WORKER_DECLINED,
            declined_at=utcnow(),
            decline_reason=DeclineReason.OTHER,
        )
    )
    await session.commit()

    await drain()

    assert esign.sent == {}


async def test_pm_can_retry_a_waiting_contract(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    created, _, pm = await _engage(client, session, settings)
    await drain()
    esign.sent.clear()

    response = await client.post(
        f"/api/v1/engagements/{created['id']}/contract/retry", headers=bearer(settings, pm)
    )
    await drain()

    assert response.status_code == 202
    assert list(esign.sent) == [(await _engagement(session, created["id"])).id]


async def test_retry_is_refused_once_signed_and_for_unstaffed_pms(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    created, _, pm = await _engage(client, session, settings)
    await drain()
    await _sign(
        client, settings, (await _engagement(session, created["id"])).esign_envelope_id or ""
    )
    outsider = await make_user(session, role=UserRole.PM)
    url = f"/api/v1/engagements/{created['id']}/contract/retry"

    signed = await client.post(url, headers=bearer(settings, pm))
    hidden = await client.post(url, headers=bearer(settings, outsider))

    assert (signed.status_code, signed.json()["code"]) == (409, "contract_not_retryable")
    assert (hidden.status_code, hidden.json()["code"]) == (404, "engagement_not_found")


async def test_early_signature_bills_from_midnight_utc_on_the_start_date(
    client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Drain,
) -> None:
    start = (utcnow() + timedelta(days=10)).date().isoformat()
    created, _, _ = await _engage(client, session, settings, start_date=start)
    await drain()
    await _sign(
        client, settings, (await _engagement(session, created["id"])).esign_envelope_id or ""
    )
    # The hourly job runs late: the start date was yesterday, signed days before.
    yesterday = utcnow().date() - timedelta(days=1)
    await session.execute(
        update(Engagement)
        .where(Engagement.id == created["id"])
        .values(start_date=yesterday, signed_at=utcnow() - timedelta(days=3))
    )
    await session.commit()

    async with sessionmaker() as s, s.begin():
        assert await activate_due(s) == 1

    engagement = await _engagement(session, created["id"])
    assert engagement.billable_start_at == datetime(
        yesterday.year, yesterday.month, yesterday.day, tzinfo=UTC
    )


async def test_signing_clears_the_stuck_flag(
    client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Drain,
) -> None:
    created, worker, pm = await _engage(client, session, settings)
    await drain()
    await session.execute(
        update(Engagement)
        .where(Engagement.id == created["id"])
        .values(contract_sent_at=utcnow() - timedelta(hours=73))
    )
    await session.commit()
    async with sessionmaker() as s, s.begin():
        assert await flag_stuck(s, settings) == 1
    url = f"/api/v1/workers/{worker.id}/engagements"
    before = (await client.get(url, headers=bearer(settings, pm))).json()

    await _sign(
        client, settings, (await _engagement(session, created["id"])).esign_envelope_id or ""
    )
    await drain()

    after = (await client.get(url, headers=bearer(settings, pm))).json()
    assert (before[0]["stuck"], after[0]["stuck"]) == (True, False)
    assert (await _engagement(session, created["id"])).stuck_flagged_at is None


async def test_declining_clears_the_stuck_flag(
    client: AsyncClient,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Drain,
) -> None:
    created, _, _ = await _engage(client, session, settings)
    await drain()
    await session.execute(
        update(Engagement).where(Engagement.id == created["id"]).values(stuck_flagged_at=utcnow())
    )
    await session.commit()

    await _sign(
        client,
        settings,
        (await _engagement(session, created["id"])).esign_envelope_id or "",
        event="declined",
    )

    assert (await _engagement(session, created["id"])).stuck_flagged_at is None


async def test_payroll_is_signalled_late_for_a_completed_engagement(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    payroll: FakePayrollAdapter,
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm])).id,
        status=EngagementStatus.COMPLETED,
    )
    engagement.billable_start_at = utcnow() - timedelta(days=5)
    await session.commit()

    async with sessionmaker() as s, s.begin():
        await signal_payroll(s, payroll, engagement.id)

    await session.refresh(engagement)
    assert engagement.payroll_signaled_at is not None
    assert list(payroll.activations) == [engagement.id]


async def test_payroll_is_not_signalled_before_activation(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    payroll: FakePayrollAdapter,
) -> None:
    worker, _ = await make_ready_worker(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session)).id,
        status=EngagementStatus.CANCELLED,
    )

    async with sessionmaker() as s, s.begin():
        await signal_payroll(s, payroll, engagement.id)

    assert payroll.activations == {}

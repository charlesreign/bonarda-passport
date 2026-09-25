from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.engagements.enums import CancelCause, EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.queries import standing_records
from app.modules.identity.models import UserAccount
from app.modules.integrations.service import FakeEsignAdapter
from app.modules.passport.models import Worker
from app.modules.roster.models import RosterProfile
from tests.support import (
    bearer,
    engagement_terms,
    esign_webhook,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


def _decline_url(engagement_id: object) -> str:
    return f"/api/v1/workers/me/engagements/{engagement_id}/decline"


async def _offer(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> tuple[dict[str, Any], Worker, UserAccount, UserAccount]:
    """A PM offers a first-time engagement; returns (engagement, worker,
    worker account, pm)."""
    pm = await make_user(session, role=UserRole.PM)
    project = await make_project(session, staff=[pm])
    worker, account = await make_ready_worker(session, email="ama@example.com")
    response = await client.post(
        f"/api/v1/workers/{worker.id}/engagements",
        json=engagement_terms(project.id),
        headers=bearer(settings, pm),
    )
    assert response.status_code == 201
    return response.json(), worker, account, pm


async def _row(session: AsyncSession, engagement_id: object) -> Engagement:
    row = await session.get(Engagement, engagement_id)
    assert row is not None
    await session.refresh(row)
    return row


async def _events(session: AsyncSession, engagement_id: object) -> list[OutboxEvent]:
    rows = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
    return [row for row in rows if str(row.aggregate_id) == str(engagement_id)]


async def test_worker_declines_before_the_contract_is_sent(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    drain: Drain,
    esign: FakeEsignAdapter,
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)

    response = await client.post(
        _decline_url(offer["id"]),
        json={"reason": "dates", "note": "  I start another contract that week  "},
        headers=bearer(settings, account),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["decline"]["cause"] == "worker_declined"
    assert body["decline"]["reason"] == "dates"
    assert body["decline"]["note"] == "I start another contract that week"
    await drain()
    assert esign.sent == {}
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "engagement.declined"))
    ).one()
    assert audit.actor_id == account.id
    assert audit.after == {"reason": "dates"}
    types = [e.event_type for e in await _events(session, offer["id"])]
    assert "engagements.contract_void_requested" not in types


async def test_declining_a_sent_contract_asks_to_void_the_envelope(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    await drain()
    envelope = (await _row(session, offer["id"])).esign_envelope_id

    response = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert response.status_code == 200
    void = [
        e
        for e in await _events(session, offer["id"])
        if e.event_type == "engagements.contract_void_requested"
    ]
    assert [e.payload["envelope_id"] for e in void] == [envelope]


async def test_a_replayed_decline_keeps_the_first_answer(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    first = await client.post(
        _decline_url(offer["id"]), json={"reason": "dates"}, headers=bearer(settings, account)
    )

    again = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["decline"]["reason"] == "dates"
    declined = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "engagement.declined"))
    ).all()
    assert len(declined) == 1


async def test_a_signed_offer_cannot_be_declined(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)
    await drain()
    envelope = (await _row(session, offer["id"])).esign_envelope_id or ""
    body, headers = esign_webhook(settings, {"envelope_id": envelope, "event": "signed"})
    assert (
        await client.post("/api/v1/webhooks/esign", content=body, headers=headers)
    ).status_code == 204

    response = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert (response.status_code, response.json()["code"]) == (409, "engagement_not_declinable")


async def test_an_offer_declined_at_the_provider_cannot_be_declined_again(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_ready_worker(session)
    project = await make_project(session)
    engagement = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=project.id,
        status=EngagementStatus.CANCELLED,
        cancel_cause=CancelCause.ESIGN_DECLINED,
    )

    response = await client.post(
        _decline_url(engagement.id), json={"reason": "rate"}, headers=bearer(settings, account)
    )

    assert (response.status_code, response.json()["code"]) == (409, "engagement_not_declinable")


async def test_only_the_offered_worker_can_decline(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    offer, _, _, pm = await _offer(client, session, settings)
    _, stranger = await make_ready_worker(session, email="kwame@example.com")

    other = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, stranger)
    )
    staff = await client.post(
        _decline_url(offer["id"]), json={"reason": "rate"}, headers=bearer(settings, pm)
    )

    assert (other.status_code, other.json()["code"]) == (404, "engagement_not_found")
    assert (staff.status_code, staff.json()["code"]) == (403, "permission_denied")
    assert (await _row(session, offer["id"])).status is EngagementStatus.PENDING_SIGNATURE


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"reason": "money"}, 422),
        ({"reason": "rate", "note": "x" * 501}, 422),
        ({"reason": "rate", "worker_id": "00000000-0000-0000-0000-000000000000"}, 422),
        ({}, 422),
    ],
)
async def test_decline_bodies_are_validated(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    payload: dict[str, object],
    status: int,
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)

    response = await client.post(
        _decline_url(offer["id"]), json=payload, headers=bearer(settings, account)
    )

    assert response.status_code == status


async def test_a_blank_note_is_stored_as_none(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    offer, _, account, _ = await _offer(client, session, settings)

    response = await client.post(
        _decline_url(offer["id"]),
        json={"reason": "other", "note": "   "},
        headers=bearer(settings, account),
    )

    assert response.json()["decline"]["note"] is None
    assert (await _row(session, offer["id"])).decline_note is None


async def test_a_decline_counts_toward_neither_standing_nor_the_roster(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    offer, worker, account, _ = await _offer(client, session, settings)
    past = await make_project(session, name="Past project")
    completed = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=past.id,
        start_date=utcnow().date() - timedelta(days=60),
    )

    response = await client.post(
        _decline_url(offer["id"]), json={"reason": "scope"}, headers=bearer(settings, account)
    )
    assert response.status_code == 200
    await drain()
    await refresh_roster(session)

    # Only the completed engagement counts; the declined offer is invisible to both.
    records = await standing_records(session, worker.id)
    assert [r.engagement_id for r in records] == [completed.id]
    profile = await session.get(RosterProfile, worker.id)
    assert profile is not None
    await session.refresh(profile)
    assert profile.engagements_total == 1

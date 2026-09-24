from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from tests.support import bearer, make_user, make_worker

URL = "/api/v1/workers/me/consents"


async def test_consents_default_to_not_granted(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)

    response = await client.get(URL, headers=bearer(settings, account))

    assert [(c["purpose"], c["granted"], c["legal_basis"]) for c in response.json()] == [
        ("cross_region_matching", False, None),
        ("external_prefill", False, None),
    ]


async def test_granting_consent_is_audited_and_published(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, account = await make_worker(session)

    response = await client.put(
        f"{URL}/cross_region_matching", json={"granted": True}, headers=bearer(settings, account)
    )

    body = response.json()
    assert (body["granted"], body["legal_basis"]) == (True, "consent")
    assert body["granted_at"] is not None
    audit = (await session.scalars(select(AuditLog))).one()
    assert (audit.action, audit.target_id) == ("consent.granted", worker.id)
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.payload == {
        "aggregate_id": str(worker.id),
        "purpose": "cross_region_matching",
        "granted": True,
    }


async def test_withdrawing_consent_records_when(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)

    response = await client.put(
        f"{URL}/cross_region_matching", json={"granted": False}, headers=headers
    )

    body = response.json()
    assert body["granted"] is False
    assert body["withdrawn_at"] is not None
    actions = (await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["consent.granted", "consent.withdrawn"]


async def test_setting_the_current_value_changes_nothing(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)

    await client.put(f"{URL}/external_prefill", json={"granted": False}, headers=headers)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)

    assert len((await session.scalars(select(AuditLog))).all()) == 1
    assert len((await session.scalars(select(OutboxEvent))).all()) == 1


async def test_unknown_purpose_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)

    response = await client.put(
        f"{URL}/marketing", json={"granted": True}, headers=bearer(settings, account)
    )

    assert response.status_code == 422


async def test_staff_have_no_consents_endpoint(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.get(URL, headers=bearer(settings, pm))

    assert response.status_code == 403


async def test_the_audit_row_records_the_previous_value(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, account = await make_worker(session)
    headers = bearer(settings, account)
    await client.put(f"{URL}/cross_region_matching", json={"granted": True}, headers=headers)

    await client.put(f"{URL}/cross_region_matching", json={"granted": False}, headers=headers)

    withdrawn = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "consent.withdrawn"))
    ).one()
    assert (withdrawn.before, withdrawn.after) == (
        {"purpose": "cross_region_matching", "granted": True},
        {"purpose": "cross_region_matching", "granted": False},
    )

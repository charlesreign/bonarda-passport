import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.pagination import encode_cursor
from app.core.time import utcnow
from app.modules.governance.models import Dispute
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import StandingTier
from app.modules.standing.models import StandingChange
from tests.support import (
    bearer,
    make_dispute,
    make_engagement,
    make_feedback,
    make_project,
    make_user,
    make_worker,
)

URL = "/api/v1/disputes"
REASON = "The feedback describes a different project."
NOTES = "Checked with the PM: the feedback was meant for another worker."


async def _reviewed_engagement(session: AsyncSession) -> tuple[UserAccount, UUID, UUID]:
    """A worker's account, one of their completed engagements, and its feedback."""
    pm = await make_user(session, role=UserRole.PM)
    worker, account = await make_worker(session)
    project = await make_project(session, staff=[pm])
    engagement = await make_engagement(session, worker_id=worker.id, project_id=project.id)
    feedback = await make_feedback(session, engagement_id=engagement.id, reviewer_id=pm.id)
    return account, engagement.id, feedback.id


def _body(target_type: str, target_id: UUID | str) -> dict[str, str]:
    return {"target_type": target_type, "target_id": str(target_id), "reason": REASON}


async def test_worker_disputes_feedback_from_their_passport(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, _ = await _reviewed_engagement(session)
    headers = bearer(settings, account)
    history = (
        await client.get(f"/api/v1/workers/{account.worker_id}/engagements", headers=headers)
    ).json()
    feedback_id = history[0]["feedback"]["id"]

    response = await client.post(URL, json=_body("feedback", feedback_id), headers=headers)

    body = response.json()
    assert response.status_code == 201
    assert (body["status"], body["worker_id"], body["target_id"]) == (
        "open",
        str(account.worker_id),
        feedback_id,
    )
    remaining = datetime.fromisoformat(body["due_at"]) - utcnow()
    assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "dispute.filed"))
    ).one()
    assert REASON not in json.dumps([audit.before, audit.after])
    event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.dispute_filed")
        )
    ).one()
    assert REASON not in json.dumps(event.payload)


async def test_worker_disputes_an_engagement_and_a_standing_change(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, engagement_id, _ = await _reviewed_engagement(session)
    assert account.worker_id is not None
    change = StandingChange(
        worker_id=account.worker_id,
        previous_tier=StandingTier.UNRATED,
        new_tier=StandingTier.TIER_1,
        contributing_factors={},
    )
    session.add(change)
    await session.commit()
    headers = bearer(settings, account)

    standing = (await client.get("/api/v1/workers/me/standing", headers=headers)).json()
    for target_type, target_id in (
        ("engagement", engagement_id),
        ("standing_change", standing["history"][0]["id"]),
    ):
        response = await client.post(URL, json=_body(target_type, target_id), headers=headers)
        assert response.status_code == 201, response.json()

    assert standing["history"][0]["id"] == str(change.id)


async def test_a_worker_cannot_dispute_someone_elses_record(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    _, _, feedback_id = await _reviewed_engagement(session)
    _, stranger = await make_worker(session, full_name="Ama Owusu")

    for target_id in (feedback_id, uuid4()):
        response = await client.post(
            URL, json=_body("feedback", target_id), headers=bearer(settings, stranger)
        )
        assert (response.status_code, response.json()["code"]) == (
            404,
            "dispute_target_not_found",
        )
    assert (await session.scalars(select(Dispute))).all() == []


async def test_a_record_has_at_most_one_open_dispute(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, feedback_id = await _reviewed_engagement(session)
    headers = bearer(settings, account)

    first = await client.post(URL, json=_body("feedback", feedback_id), headers=headers)
    second = await client.post(URL, json=_body("feedback", feedback_id), headers=headers)

    assert first.status_code == 201
    assert (second.status_code, second.json()["code"]) == (409, "dispute_already_open")
    assert len((await session.scalars(select(Dispute))).all()) == 1


@pytest.mark.parametrize("role", [UserRole.PM, UserRole.PEOPLE_OPS])
async def test_only_workers_file_disputes(
    client: AsyncClient, session: AsyncSession, settings: Settings, role: UserRole
) -> None:
    _, _, feedback_id = await _reviewed_engagement(session)
    staff = await make_user(session, role=role)

    response = await client.post(
        URL, json=_body("feedback", feedback_id), headers=bearer(settings, staff)
    )

    assert (response.status_code, response.json()["code"]) == (403, "permission_denied")


async def test_people_ops_see_the_queue_and_workers_see_their_own(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account_a, _, feedback_a = await _reviewed_engagement(session)
    account_b, _, feedback_b = await _reviewed_engagement(session)
    for account, feedback_id in ((account_a, feedback_a), (account_b, feedback_b)):
        filed = await client.post(
            URL, json=_body("feedback", feedback_id), headers=bearer(settings, account)
        )
        assert filed.status_code == 201
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    pm = await make_user(session, role=UserRole.PM)

    queue = (await client.get(URL, params={"status": "open"}, headers=bearer(settings, ops))).json()
    own = (await client.get(URL, headers=bearer(settings, account_a))).json()
    pm_view = await client.get(URL, headers=bearer(settings, pm))

    assert [d["worker_id"] for d in queue["items"]] == [
        str(account_a.worker_id),
        str(account_b.worker_id),
    ]
    assert [d["worker_id"] for d in own["items"]] == [str(account_a.worker_id)]
    assert (pm_view.status_code, pm_view.json()["code"]) == (403, "permission_denied")


async def test_the_queue_pages_in_due_order(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    now = utcnow()
    disputes = [
        await make_dispute(session, worker_id=worker.id, due_at=now + timedelta(days=days))
        for days in (3, 1, 2)
    ]
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    headers = bearer(settings, ops)

    first = (await client.get(URL, params={"limit": 2}, headers=headers)).json()
    second = (
        await client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)
    ).json()
    tampered = await client.get(
        URL, params={"cursor": encode_cursor({"due_at": "yesterday", "id": "x"})}, headers=headers
    )

    ids = [d["id"] for d in first["items"] + second["items"]]
    assert ids == [str(disputes[1].id), str(disputes[2].id), str(disputes[0].id)]
    assert second["next_cursor"] is None
    assert (tampered.status_code, tampered.json()["code"]) == (400, "invalid_cursor")


async def test_people_ops_resolve_a_dispute_once(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, feedback_id = await _reviewed_engagement(session)
    filed = (
        await client.post(
            URL, json=_body("feedback", feedback_id), headers=bearer(settings, account)
        )
    ).json()
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    decision = {"resolution": "upheld", "resolution_notes": NOTES}

    response = await client.patch(
        f"{URL}/{filed['id']}", json=decision, headers=bearer(settings, ops)
    )
    again = await client.patch(f"{URL}/{filed['id']}", json=decision, headers=bearer(settings, ops))

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["resolution"], body["resolver_id"]) == (
        "resolved",
        "upheld",
        str(ops.id),
    )
    assert body["resolution_notes"] == NOTES
    assert (again.status_code, again.json()["code"]) == (409, "dispute_already_resolved")
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "dispute.resolved"))
    ).one()
    assert (audit.before, audit.after) == (
        {"status": "open"},
        {"status": "resolved", "resolution": "upheld"},
    )
    event = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "governance.dispute_resolved")
        )
    ).one()
    assert event.payload["resolution"] == "upheld"
    assert NOTES not in json.dumps(event.payload)


async def test_workers_cannot_resolve_and_unknown_disputes_are_404(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    account, _, feedback_id = await _reviewed_engagement(session)
    filed = (
        await client.post(
            URL, json=_body("feedback", feedback_id), headers=bearer(settings, account)
        )
    ).json()
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    decision = {"resolution": "rejected", "resolution_notes": NOTES}

    by_worker = await client.patch(
        f"{URL}/{filed['id']}", json=decision, headers=bearer(settings, account)
    )
    unknown = await client.patch(f"{URL}/{uuid4()}", json=decision, headers=bearer(settings, ops))

    assert (by_worker.status_code, by_worker.json()["code"]) == (403, "permission_denied")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "dispute_not_found")

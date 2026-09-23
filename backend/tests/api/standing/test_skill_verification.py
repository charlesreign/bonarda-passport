from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.standing.models import SkillEvidence
from tests.support import (
    POSITIVE_ANSWERS,
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
)

Drain = Callable[[], Awaitable[None]]


async def _review(
    client: AsyncClient,
    session: AsyncSession,
    settings: Settings,
    *,
    pm: UserAccount,
    worker_id: UUID,
    skill_id: UUID,
) -> None:
    project = await make_project(session, staff=[pm], name=f"Project {uuid4().hex[:6]}")
    engagement = await make_engagement(session, worker_id=worker_id, project_id=project.id)
    response = await client.post(
        f"/api/v1/engagements/{engagement.id}/feedback",
        json={"structured_answers": POSITIVE_ANSWERS, "skill_ids_demonstrated": [str(skill_id)]},
        headers=bearer(settings, pm),
    )
    assert response.status_code == 201


async def _claim_status(session: AsyncSession, worker_id: UUID) -> VerificationStatus:
    claim = (
        await session.scalars(select(SkillClaim).where(SkillClaim.worker_id == worker_id))
    ).one()
    await session.refresh(claim)
    return claim.verification_status


async def test_two_distinct_reviewers_verify_a_skill(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)

    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await drain()
    after_one = await _claim_status(session, worker.id)
    await _review(client, session, settings, pm=kwame, worker_id=worker.id, skill_id=skill.id)
    await drain()

    assert after_one is VerificationStatus.SELF_REPORTED
    assert await _claim_status(session, worker.id) is VerificationStatus.BONARDA_VERIFIED
    verified = (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "standing.skill_verified")
        )
    ).one()
    assert verified.payload["skill_id"] == str(skill.id)
    audit = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "skill.verified"))
    ).one()
    assert (audit.target_id, audit.after) == (worker.id, {"skill_id": str(skill.id)})


async def test_the_same_reviewer_counts_once(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)

    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await drain()

    assert await _claim_status(session, worker.id) is VerificationStatus.SELF_REPORTED
    assert len((await session.scalars(select(SkillEvidence))).all()) == 1


async def test_a_removed_claim_is_not_verified_but_evidence_is_kept(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, _ = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    ama = await make_user(session, role=UserRole.PM)
    kwame = await make_user(session, role=UserRole.PM)
    await _review(client, session, settings, pm=ama, worker_id=worker.id, skill_id=skill.id)
    await _review(client, session, settings, pm=kwame, worker_id=worker.id, skill_id=skill.id)
    await session.execute(delete(SkillClaim).where(SkillClaim.worker_id == worker.id))
    await session.commit()

    await drain()

    assert len((await session.scalars(select(SkillEvidence))).all()) == 2
    assert (
        await session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "standing.skill_verified")
        )
    ).all() == []


async def test_verified_skill_shows_on_the_worker_passport(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    worker, account = await make_ready_worker(session)
    skill = (await session.scalars(select(Skill))).one()
    for _ in range(2):
        pm = await make_user(session, role=UserRole.PM)
        await _review(client, session, settings, pm=pm, worker_id=worker.id, skill_id=skill.id)
    await drain()

    me = await client.get("/api/v1/workers/me", headers=bearer(settings, account))

    assert me.json()["skills"][0]["verification_status"] == "bonarda_verified"

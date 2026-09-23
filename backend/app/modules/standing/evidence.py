from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.modules.passport.service import verify_skill
from app.modules.standing.repository import SkillEvidenceRepository
from app.modules.standing.schemas import SkillVerified


async def mark_verified(session: AsyncSession, worker_id: UUID, skill_id: UUID) -> bool:
    if not await verify_skill(session, worker_id, skill_id):
        return False
    await write_audit(
        session,
        actor=None,
        action="skill.verified",
        target_type="worker",
        target_id=worker_id,
        after={"skill_id": str(skill_id)},
    )
    await emit_event(session, SkillVerified(aggregate_id=worker_id, skill_id=skill_id))
    return True


async def record_skill_evidence(
    session: AsyncSession,
    *,
    engagement_id: UUID,
    worker_id: UUID,
    reviewer_id: UUID | None,
    skill_ids: Sequence[UUID],
    min_reviewers: int,
) -> list[UUID]:
    """FR-2.2: a skill becomes bonarda_verified once distinct reviewers who saw
    it demonstrated reach the policy threshold. Returns newly verified skills."""
    if reviewer_id is None:
        return []
    evidence = SkillEvidenceRepository(session)
    verified = []
    for skill_id in dict.fromkeys(skill_ids):
        await evidence.add(
            worker_id=worker_id,
            skill_id=skill_id,
            engagement_id=engagement_id,
            reviewer_id=reviewer_id,
        )
        if await evidence.distinct_reviewers(
            worker_id, skill_id
        ) >= min_reviewers and await mark_verified(session, worker_id, skill_id):
            verified.append(skill_id)
    return verified


async def promote_skills(session: AsyncSession, min_reviewers: int) -> int:
    """Verifies every claim whose evidence already meets the threshold, e.g.
    after a policy lowers it."""
    promoted = 0
    for worker_id, skill_id in await SkillEvidenceRepository(session).pairs_meeting(min_reviewers):
        if await mark_verified(session, worker_id, skill_id):
            promoted += 1
    return promoted

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.standing.models import SkillEvidence, StandingChange


class StandingChangeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, change: StandingChange) -> StandingChange:
        self.session.add(change)
        return change

    async def list_for_worker(self, worker_id: UUID, limit: int) -> list[StandingChange]:
        stmt = (
            select(StandingChange)
            .where(StandingChange.worker_id == worker_id)
            .order_by(StandingChange.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())


class SkillEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, *, worker_id: UUID, skill_id: UUID, engagement_id: UUID, reviewer_id: UUID
    ) -> None:
        await self.session.execute(
            pg_insert(SkillEvidence)
            .values(
                worker_id=worker_id,
                skill_id=skill_id,
                engagement_id=engagement_id,
                reviewer_id=reviewer_id,
            )
            .on_conflict_do_nothing(constraint="uq_skill_evidence_worker_skill_reviewer")
        )

    async def distinct_reviewers(self, worker_id: UUID, skill_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count(func.distinct(SkillEvidence.reviewer_id))).where(
                SkillEvidence.worker_id == worker_id,
                SkillEvidence.skill_id == skill_id,
                SkillEvidence.reviewer_id.is_not(None),
            )
        )
        return int(count or 0)

    async def pairs_meeting(self, min_reviewers: int) -> list[tuple[UUID, UUID]]:
        stmt = (
            select(SkillEvidence.worker_id, SkillEvidence.skill_id)
            .where(SkillEvidence.reviewer_id.is_not(None))
            .group_by(SkillEvidence.worker_id, SkillEvidence.skill_id)
            .having(func.count(func.distinct(SkillEvidence.reviewer_id)) >= min_reviewers)
        )
        return [(worker_id, skill_id) for worker_id, skill_id in await self.session.execute(stmt)]

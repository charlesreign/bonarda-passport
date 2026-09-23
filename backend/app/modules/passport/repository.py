from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.passport.models import Skill, SkillClaim, Worker


class WorkerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, worker_id: UUID) -> Worker | None:
        return await self.session.get(Worker, worker_id)

    def add(self, worker: Worker) -> Worker:
        self.session.add(worker)
        return worker


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, skill_id: UUID) -> Skill | None:
        return await self.session.get(Skill, skill_id)

    async def get_by_slug(self, slug: str) -> Skill | None:
        return await self.session.scalar(select(Skill).where(Skill.slug == slug))

    async def search(self, q: str | None, limit: int) -> list[Skill]:
        stmt = select(Skill).order_by(Skill.slug).limit(limit)
        if q:
            # autoescape: '%' and '_' in the term match literally.
            stmt = stmt.where(
                or_(
                    Skill.slug.icontains(q, autoescape=True),
                    func.jsonb_extract_path_text(Skill.name_i18n, "en").icontains(
                        q, autoescape=True
                    ),
                    func.jsonb_extract_path_text(Skill.name_i18n, "fr").icontains(
                        q, autoescape=True
                    ),
                )
            )
        return list((await self.session.scalars(stmt)).all())

    def add(self, skill: Skill) -> Skill:
        self.session.add(skill)
        return skill


class SkillClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_worker(self, worker_id: UUID) -> list[tuple[SkillClaim, Skill]]:
        rows = await self.session.execute(
            select(SkillClaim, Skill)
            .join(Skill, Skill.id == SkillClaim.skill_id)
            .where(SkillClaim.worker_id == worker_id)
            .order_by(Skill.slug)
        )
        return [(claim, skill) for claim, skill in rows.all()]

    async def get(self, worker_id: UUID, skill_id: UUID) -> SkillClaim | None:
        return await self.session.scalar(
            select(SkillClaim).where(
                SkillClaim.worker_id == worker_id, SkillClaim.skill_id == skill_id
            )
        )

    def add(self, claim: SkillClaim) -> SkillClaim:
        self.session.add(claim)
        return claim

    async def delete(self, claim: SkillClaim) -> None:
        await self.session.delete(claim)

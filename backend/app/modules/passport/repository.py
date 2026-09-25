from datetime import date
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.passport.enums import ConsentPurpose, WorkerStatus
from app.modules.passport.models import Consent, Skill, SkillClaim, Worker


class WorkerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_update(self, worker_id: UUID) -> Worker | None:
        return await self.session.scalar(
            select(Worker).where(Worker.id == worker_id).with_for_update(key_share=True)
        )

    async def dormant_before(self, cutoff: date) -> list[UUID]:
        """Dormant workers idle since before `cutoff` (retention, spec §6.6)."""
        rows = await self.session.scalars(
            select(Worker.id)
            .where(
                Worker.status == WorkerStatus.DORMANT,
                Worker.dormant_since.is_not(None),
                Worker.dormant_since < cutoff,
            )
            .order_by(Worker.id)
        )
        return list(rows.all())

    async def tier_counts(self) -> list[tuple[str, str, int]]:
        """(data_region, standing_tier, count) for the talent pool."""
        rows = await self.session.execute(
            select(Worker.data_region, Worker.standing_tier, func.count())
            .where(Worker.status.in_((WorkerStatus.ACTIVE, WorkerStatus.DORMANT)))
            .group_by(Worker.data_region, Worker.standing_tier)
        )
        return [(region, tier.value, int(n)) for region, tier, n in rows]

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

    async def get_for_update(self, worker_id: UUID, skill_id: UUID) -> SkillClaim | None:
        # Lock the claim before checking verification_status: a concurrent
        # verification (skills.py ClaimService.remove) must not land between
        # the check and the delete.
        return await self.session.scalar(
            select(SkillClaim)
            .where(SkillClaim.worker_id == worker_id, SkillClaim.skill_id == skill_id)
            .with_for_update()
        )

    def add(self, claim: SkillClaim) -> SkillClaim:
        self.session.add(claim)
        return claim

    async def delete(self, claim: SkillClaim) -> None:
        await self.session.delete(claim)


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_worker(self, worker_id: UUID) -> list[Consent]:
        return list(
            (
                await self.session.scalars(select(Consent).where(Consent.worker_id == worker_id))
            ).all()
        )

    async def get(self, worker_id: UUID, purpose: ConsentPurpose) -> Consent | None:
        return await self.session.scalar(
            select(Consent).where(Consent.worker_id == worker_id, Consent.purpose == purpose)
        )

    async def delete_for_worker(self, worker_id: UUID) -> None:
        await self.session.execute(delete(Consent).where(Consent.worker_id == worker_id))

    def add(self, consent: Consent) -> Consent:
        self.session.add(consent)
        return consent

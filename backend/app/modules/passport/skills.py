from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.passport.dependencies import WorkerActor
from app.modules.passport.enums import ClaimSource, VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from app.modules.passport.repository import SkillClaimRepository, SkillRepository
from app.modules.passport.schemas import SkillCreate, WorkerSkill, WorkerUpdated


class SkillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skills = SkillRepository(session)

    async def create(self, actor: Actor, data: SkillCreate) -> Skill:
        if await self.skills.get_by_slug(data.slug) is not None:
            raise Conflict("A skill with this slug exists", code="skill_slug_taken")
        names = {str(locale): name.strip() for locale, name in data.name_i18n.items()}
        try:
            async with self.session.begin_nested():
                skill = self.skills.add(Skill(slug=data.slug, name_i18n=names))
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_skills_slug":
                raise
            raise Conflict("A skill with this slug exists", code="skill_slug_taken") from exc
        await write_audit(
            self.session,
            actor=actor,
            action="skill.created",
            target_type="skill",
            target_id=skill.id,
            after={"slug": skill.slug, "name_i18n": skill.name_i18n},
        )
        return skill

    async def search(self, q: str | None, limit: int) -> list[Skill]:
        return await self.skills.search(q, limit)


class ClaimService:
    """Self-reported claims. Verification is earned through reviews (Plan 3),
    never set here (FR-2.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skills = SkillRepository(session)
        self.claims = SkillClaimRepository(session)

    async def claim(self, who: WorkerActor, skill_id: UUID) -> WorkerSkill:
        skill = await self.skills.get(skill_id)
        if skill is None:
            raise NotFound("Skill not found", code="skill_not_found")
        if await self.claims.get(who.worker_id, skill_id) is not None:
            raise Conflict("You already list this skill", code="skill_already_claimed")
        try:
            async with self.session.begin_nested():
                claim = self.claims.add(
                    SkillClaim(
                        worker_id=who.worker_id,
                        skill_id=skill_id,
                        verification_status=VerificationStatus.SELF_REPORTED,
                        source=ClaimSource.SELF,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_skill_claims_worker_skill":
                raise
            raise Conflict("You already list this skill", code="skill_already_claimed") from exc
        await emit_event(self.session, WorkerUpdated(aggregate_id=who.worker_id, fields=["skills"]))
        return WorkerSkill(
            skill_id=skill.id, slug=skill.slug, verification_status=claim.verification_status
        )

    async def remove(self, who: WorkerActor, skill_id: UUID) -> None:
        claim = await self.claims.get(who.worker_id, skill_id)
        if claim is None:
            raise NotFound("You do not list this skill", code="claim_not_found")
        if claim.verification_status is VerificationStatus.BONARDA_VERIFIED:
            raise Conflict(
                "Verified skills are backed by reviews and cannot be removed",
                code="skill_verified_locked",
            )
        await self.claims.delete(claim)
        await emit_event(self.session, WorkerUpdated(aggregate_id=who.worker_id, fields=["skills"]))

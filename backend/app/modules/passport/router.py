from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.identity.service import CurrentActor, Permission, require_permission
from app.modules.passport.dependencies import WorkerEditor
from app.modules.passport.schemas import SkillClaimCreate, SkillCreate, SkillRead, WorkerSkill
from app.modules.passport.skills import ClaimService, SkillService

router = APIRouter(prefix="/api/v1", tags=["passport"])

SkillManager = Annotated[Actor, Depends(require_permission(Permission.SKILL_MANAGE))]


@router.get("/skills")
async def search_skills(
    actor: CurrentActor,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SkillRead]:
    skills = await SkillService(session).search(q, limit)
    return [SkillRead.model_validate(s) for s in skills]


@router.post("/skills", status_code=201)
async def create_skill(body: SkillCreate, actor: SkillManager, session: SessionDep) -> SkillRead:
    return SkillRead.model_validate(await SkillService(session).create(actor, body))


@router.post("/workers/me/skills", status_code=201)
async def claim_skill(
    body: SkillClaimCreate, who: WorkerEditor, session: SessionDep
) -> WorkerSkill:
    return await ClaimService(session).claim(who, body.skill_id)


@router.delete("/workers/me/skills/{skill_id}", status_code=204)
async def remove_skill_claim(skill_id: UUID, who: WorkerEditor, session: SessionDep) -> None:
    await ClaimService(session).remove(who, skill_id)

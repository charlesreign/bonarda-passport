from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.modules.identity.service import (
    CurrentActor,
    Permission,
    Visibility,
    require_permission,
    require_visibility,
)
from app.modules.passport.consents import ConsentService
from app.modules.passport.dependencies import WorkerEditor, WorkerReader
from app.modules.passport.enums import ConsentPurpose
from app.modules.passport.invitations import InvitationService
from app.modules.passport.profile import ProfileService
from app.modules.passport.schemas import (
    ConsentRead,
    ConsentUpdate,
    InvitationCreate,
    InvitationRead,
    SkillClaimCreate,
    SkillCreate,
    SkillRead,
    WorkerSelf,
    WorkerSkill,
    WorkerUpdate,
    WorkerView,
)
from app.modules.passport.skills import ClaimService, SkillService

router = APIRouter(prefix="/api/v1", tags=["passport"])

SkillManager = Annotated[Actor, Depends(require_permission(Permission.SKILL_MANAGE))]
Inviter = Annotated[Actor, Depends(require_permission(Permission.WORKER_INVITE))]


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


@router.get("/workers/me")
async def read_my_passport(who: WorkerReader, session: SessionDep) -> WorkerSelf:
    return await ProfileService(session).view_self(who)


@router.patch("/workers/me")
async def update_my_passport(
    body: WorkerUpdate, who: WorkerEditor, session: SessionDep
) -> WorkerSelf:
    return await ProfileService(session).update_self(who, body)


@router.post("/workers/me/onboarding/complete")
async def complete_onboarding(who: WorkerEditor, session: SessionDep) -> WorkerSelf:
    return await ProfileService(session).complete_onboarding(who)


@router.get("/workers/me/consents")
async def list_my_consents(who: WorkerReader, session: SessionDep) -> list[ConsentRead]:
    return await ConsentService(session).list_for(who.worker_id)


@router.put("/workers/me/consents/{purpose}")
async def set_my_consent(
    purpose: ConsentPurpose, body: ConsentUpdate, who: WorkerEditor, session: SessionDep
) -> ConsentRead:
    return await ConsentService(session).set(who, purpose, body.granted)


@router.post(
    "/workers/invitations",
    status_code=201,
    responses={200: {"model": InvitationRead, "description": "Invitation resent"}},
)
async def invite_worker(
    body: InvitationCreate,
    actor: Inviter,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
) -> InvitationRead:
    result = await InvitationService(session, settings).invite(actor, body)
    if result.resent:
        response.status_code = 200
    return result


@router.get("/workers/{worker_id}")
async def read_worker(
    worker_id: UUID,
    actor: CurrentActor,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> WorkerView:
    return await ProfileService(session).view(actor, worker_id, level)

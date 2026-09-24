from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.governance.enums import PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.schemas import PolicyCreate, PolicyRead
from app.modules.identity.service import Permission, require_permission

router = APIRouter(prefix="/api/v1", tags=["governance"])

PolicyProposer = Annotated[Actor, Depends(require_permission(Permission.POLICY_PROPOSE))]
PolicyActivator = Annotated[Actor, Depends(require_permission(Permission.POLICY_ACTIVATE))]


@router.get("/policies/{kind}/versions")
async def list_policy_versions(
    kind: PolicyKind, actor: PolicyProposer, session: SessionDep
) -> list[PolicyRead]:
    return await PolicyService(session).list_versions(kind)


@router.post("/policies/{kind}/versions", status_code=201)
async def propose_policy(
    kind: PolicyKind, body: PolicyCreate, actor: PolicyProposer, session: SessionDep
) -> PolicyRead:
    return PolicyRead.model_validate(await PolicyService(session).propose(actor, kind, body))


@router.post("/policies/{kind}/versions/{version}/activate")
async def activate_policy(
    kind: PolicyKind, version: int, actor: PolicyActivator, session: SessionDep
) -> PolicyRead:
    return PolicyRead.model_validate(await PolicyService(session).activate(actor, kind, version))

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.governance.audit import audit_trail
from app.modules.governance.enums import PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.schemas import AuditLogPage, PolicyCreate, PolicyRead
from app.modules.identity.service import Permission, require_permission

router = APIRouter(prefix="/api/v1", tags=["governance"])

PolicyProposer = Annotated[Actor, Depends(require_permission(Permission.POLICY_PROPOSE))]
PolicyActivator = Annotated[Actor, Depends(require_permission(Permission.POLICY_ACTIVATE))]
AuditReader = Annotated[Actor, Depends(require_permission(Permission.AUDIT_READ))]


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


@router.get("/governance/audit-log")
async def read_audit_log(
    actor: AuditReader,
    session: SessionDep,
    target_type: Annotated[str | None, Query(max_length=40)] = None,
    target_id: UUID | None = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AuditLogPage:
    return await audit_trail(
        session,
        target_type=target_type,
        target_id=target_id,
        action=action,
        cursor=cursor,
        limit=limit,
    )

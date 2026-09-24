from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.modules.governance.audit import audit_trail
from app.modules.governance.disputes import DisputeService, DisputeTargetOwners
from app.modules.governance.enums import DisputeStatus, PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.schemas import (
    AuditLogPage,
    DisputeCreate,
    DisputePage,
    DisputeRead,
    DisputeResolve,
    PolicyCreate,
    PolicyRead,
)
from app.modules.identity.service import CurrentActor, Permission, require_permission

router = APIRouter(prefix="/api/v1", tags=["governance"])

PolicyProposer = Annotated[Actor, Depends(require_permission(Permission.POLICY_PROPOSE))]
PolicyActivator = Annotated[Actor, Depends(require_permission(Permission.POLICY_ACTIVATE))]
AuditReader = Annotated[Actor, Depends(require_permission(Permission.AUDIT_READ))]
DisputeFiler = Annotated[Actor, Depends(require_permission(Permission.DISPUTE_FILE))]
DisputeResolver = Annotated[Actor, Depends(require_permission(Permission.DISPUTE_RESOLVE))]


def get_dispute_target_owners(request: Request) -> DisputeTargetOwners:
    return request.app.state.dispute_target_owners


TargetOwnersDep = Annotated[DisputeTargetOwners, Depends(get_dispute_target_owners)]


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


@router.post("/disputes", status_code=201)
async def file_dispute(
    body: DisputeCreate,
    actor: DisputeFiler,
    session: SessionDep,
    settings: SettingsDep,
    owners: TargetOwnersDep,
) -> DisputeRead:
    dispute = await DisputeService(session).file(
        actor, body, owners=owners, sla_days=settings.dispute_sla_days
    )
    return DisputeRead.model_validate(dispute)


@router.get("/disputes")
async def list_disputes(
    actor: CurrentActor,
    session: SessionDep,
    status: DisputeStatus | None = None,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DisputePage:
    return await DisputeService(session).list_for(actor, status=status, cursor=cursor, limit=limit)


@router.patch("/disputes/{dispute_id}")
async def resolve_dispute(
    dispute_id: UUID, body: DisputeResolve, actor: DisputeResolver, session: SessionDep
) -> DisputeRead:
    return DisputeRead.model_validate(
        await DisputeService(session).resolve(actor, dispute_id, body)
    )

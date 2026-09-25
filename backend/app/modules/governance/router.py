from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.core.errors import Forbidden
from app.core.time import utcnow
from app.modules.governance.audit import audit_trail
from app.modules.governance.concentration import concentration_history, governance_overview
from app.modules.governance.disputes import DisputeService, DisputeTargetOwners
from app.modules.governance.enums import DisputeStatus, PolicyKind
from app.modules.governance.policies import PolicyService
from app.modules.governance.repository import DisputeRepository
from app.modules.governance.schemas import (
    AuditLogPage,
    ConcentrationRollupRead,
    DisputeCreate,
    DisputePage,
    DisputeRead,
    DisputeResolve,
    DisputeStatusRead,
    GovernanceOverview,
    PolicyCreate,
    PolicyRead,
)
from app.modules.identity.service import (
    CurrentActor,
    Permission,
    Visibility,
    can_view_governance,
    has_permission,
    require_permission,
    require_visibility,
)

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


@router.get("/workers/{worker_id}/disputes")
async def worker_dispute_status(
    worker_id: UUID,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> list[DisputeStatusRead]:
    return [
        DisputeStatusRead.model_validate(d)
        for d in await DisputeRepository(session).status_for_worker(worker_id)
    ]


async def governance_reader(actor: CurrentActor, session: SessionDep) -> Actor:
    """People Ops and admins, plus PM leadership with the account flag
    (spec §7.2 governance endpoints)."""
    if has_permission(actor.role, Permission.GOVERNANCE_READ):
        return actor
    if await can_view_governance(session, actor.user_id):
        return actor
    raise Forbidden("Missing permission governance:read", code="permission_denied")


GovernanceReader = Annotated[Actor, Depends(governance_reader)]


@router.get("/governance/overview")
async def read_governance_overview(
    actor: GovernanceReader, session: SessionDep
) -> GovernanceOverview:
    return await governance_overview(session, utcnow())


@router.get("/governance/concentration")
async def read_concentration(
    actor: GovernanceReader,
    session: SessionDep,
    scope: Annotated[str, Query(pattern=r"^[A-Z]{2,8}$")] = "ORG",
    limit: Annotated[int, Query(ge=1, le=366)] = 30,
) -> list[ConcentrationRollupRead]:
    return await concentration_history(session, scope, limit)

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import ValidationError

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.core.errors import BadRequest, Unauthorized
from app.core.time import utcnow
from app.modules.engagements.contracts import ContractService
from app.modules.engagements.engagements import EngagementService
from app.modules.engagements.enums import EngagementPath
from app.modules.engagements.feedback import FeedbackService
from app.modules.engagements.projects import ProjectService
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import (
    CompletionRequest,
    EngagementCreate,
    EngagementRead,
    EsignWebhook,
    FeedbackCreate,
    ProjectCreate,
    ProjectRead,
    ReactivationCreate,
    ReactivationPrefill,
    StaffAssignment,
    engagement_read,
)
from app.modules.identity.service import (
    CurrentActor,
    Permission,
    Visibility,
    require_permission,
    require_visibility,
)
from app.modules.integrations.service import verify_signature

router = APIRouter(prefix="/api/v1", tags=["engagements"])

ProjectManager = Annotated[Actor, Depends(require_permission(Permission.PROJECT_MANAGE))]
EngagementCreator = Annotated[Actor, Depends(require_permission(Permission.ENGAGEMENT_CREATE))]
Reactivator = Annotated[Actor, Depends(require_permission(Permission.ENGAGEMENT_REACTIVATE))]
FeedbackReviewer = Annotated[Actor, Depends(require_permission(Permission.FEEDBACK_SUBMIT))]


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate, actor: ProjectManager, session: SessionDep, settings: SettingsDep
) -> ProjectRead:
    return await ProjectService(session, settings).create(actor, body)


@router.get("/projects")
async def list_projects(
    actor: CurrentActor, session: SessionDep, settings: SettingsDep
) -> list[ProjectRead]:
    return await ProjectService(session, settings).list_visible(actor)


@router.get("/projects/{project_id}")
async def read_project(
    project_id: UUID, actor: CurrentActor, session: SessionDep, settings: SettingsDep
) -> ProjectRead:
    return await ProjectService(session, settings).read(actor, project_id)


@router.put("/projects/{project_id}/staff")
async def set_project_staff(
    project_id: UUID,
    body: StaffAssignment,
    actor: CurrentActor,
    session: SessionDep,
    settings: SettingsDep,
) -> ProjectRead:
    return await ProjectService(session, settings).set_staff(actor, project_id, body)


@router.get("/workers/{worker_id}/engagements")
async def list_worker_engagements(
    worker_id: UUID,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> list[EngagementRead]:
    repo = EngagementRepository(session)
    engagements = await repo.list_for_worker(worker_id)
    feedback = await repo.feedback_for([e.id for e in engagements])
    return [engagement_read(e, feedback.get(e.id)) for e in engagements]


@router.post("/workers/{worker_id}/engagements", status_code=201)
async def create_first_time_engagement(
    worker_id: UUID,
    body: EngagementCreate,
    actor: EngagementCreator,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> EngagementRead:
    engagement = await EngagementService(session).create(
        actor, worker_id, body, path=EngagementPath.FIRST_TIME
    )
    return engagement_read(engagement, None)


@router.get("/workers/{worker_id}/reactivation-prefill")
async def reactivation_prefill(
    worker_id: UUID,
    project_id: Annotated[UUID, Query()],
    actor: Reactivator,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> ReactivationPrefill:
    return await EngagementService(session).prefill(actor, worker_id, project_id)


@router.post(
    "/workers/{worker_id}/reactivations",
    status_code=201,
    responses={200: {"model": EngagementRead, "description": "Replayed Idempotency-Key"}},
)
async def reactivate_worker(
    worker_id: UUID,
    body: ReactivationCreate,
    actor: Reactivator,
    session: SessionDep,
    response: Response,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EngagementRead:
    engagement, replayed = await EngagementService(session).reactivate(
        actor, worker_id, body, idempotency_key
    )
    if replayed:
        response.status_code = 200
    return engagement_read(engagement, None)


@router.post("/webhooks/esign", status_code=204)
async def esign_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_bonarda_timestamp: Annotated[str | None, Header()] = None,
    x_bonarda_signature: Annotated[str | None, Header()] = None,
) -> None:
    body = await request.body()
    if not verify_signature(
        settings.esign_webhook_secret.get_secret_value(),
        timestamp_header=x_bonarda_timestamp,
        signature_header=x_bonarda_signature,
        body=body,
        now=utcnow(),
    ):
        raise Unauthorized("Invalid webhook signature", code="webhook_signature_invalid")
    try:
        event = EsignWebhook.model_validate_json(body)
    except ValidationError as exc:
        raise BadRequest("Malformed webhook payload", code="invalid_webhook_payload") from exc
    await ContractService(session).handle_webhook(event)


@router.post("/engagements/{engagement_id}/contract/retry", status_code=202)
async def retry_contract(
    engagement_id: UUID, actor: EngagementCreator, session: SessionDep
) -> EngagementRead:
    engagement = await ContractService(session).request_retry(actor, engagement_id)
    return engagement_read(engagement, None)


@router.post("/engagements/{engagement_id}/complete")
async def complete_engagement(
    engagement_id: UUID, body: CompletionRequest, actor: EngagementCreator, session: SessionDep
) -> EngagementRead:
    engagement = await EngagementService(session).complete(actor, engagement_id, body)
    return engagement_read(engagement, None)


@router.post("/engagements/{engagement_id}/feedback", status_code=201)
async def submit_feedback(
    engagement_id: UUID, body: FeedbackCreate, actor: FeedbackReviewer, session: SessionDep
) -> EngagementRead:
    engagement, feedback = await FeedbackService(session).submit(actor, engagement_id, body)
    return engagement_read(engagement, feedback)

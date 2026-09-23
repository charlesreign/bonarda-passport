from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.modules.engagements.engagements import EngagementService
from app.modules.engagements.enums import EngagementPath
from app.modules.engagements.projects import ProjectService
from app.modules.engagements.repository import EngagementRepository
from app.modules.engagements.schemas import (
    EngagementCreate,
    EngagementRead,
    ProjectCreate,
    ProjectRead,
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

router = APIRouter(prefix="/api/v1", tags=["engagements"])

ProjectManager = Annotated[Actor, Depends(require_permission(Permission.PROJECT_MANAGE))]
EngagementCreator = Annotated[Actor, Depends(require_permission(Permission.ENGAGEMENT_CREATE))]


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

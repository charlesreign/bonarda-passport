from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.modules.engagements.projects import ProjectService
from app.modules.engagements.schemas import ProjectCreate, ProjectRead, StaffAssignment
from app.modules.identity.service import CurrentActor, Permission, require_permission

router = APIRouter(prefix="/api/v1", tags=["engagements"])

ProjectManager = Annotated[Actor, Depends(require_permission(Permission.PROJECT_MANAGE))]


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

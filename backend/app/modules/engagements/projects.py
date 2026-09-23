from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import UserRole
from app.core.errors import BadRequest, Forbidden, NotFound
from app.core.time import utcnow
from app.modules.engagements.models import Project, ProjectStaff
from app.modules.engagements.repository import ProjectRepository
from app.modules.engagements.schemas import ProjectCreate, ProjectRead, StaffAssignment
from app.modules.identity.service import Permission, active_pm_ids, has_permission
from app.modules.passport.service import existing_skill_ids

_SEES_ALL = (UserRole.PEOPLE_OPS, UserRole.ADMIN)


class ProjectService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)

    async def create(self, actor: Actor, data: ProjectCreate) -> ProjectRead:
        if data.data_region not in self.settings.data_regions:
            raise BadRequest("Unknown data region", code="unknown_data_region")
        skill_ids = list(dict.fromkeys(data.required_skill_ids))
        if set(skill_ids) - await existing_skill_ids(self.session, skill_ids):
            raise BadRequest("Unknown skill id", code="unknown_skill")
        project = self.projects.add(
            Project(
                name=data.name.strip(),
                client_name=data.client_name,
                data_region=data.data_region,
                required_skill_ids=skill_ids,
                starts_on=data.starts_on,
                ends_on=data.ends_on,
                created_by_id=actor.user_id,
            )
        )
        await self.session.flush()
        if actor.role is UserRole.PM:
            self.projects.add_staff(
                ProjectStaff(
                    project_id=project.id, user_account_id=actor.user_id, active_from=utcnow()
                )
            )
            await self.session.flush()
        await write_audit(
            self.session,
            actor=actor,
            action="project.created",
            target_type="project",
            target_id=project.id,
            after={"name": project.name, "data_region": project.data_region},
        )
        return await self._read(project)

    async def _read(self, project: Project) -> ProjectRead:
        staff = await self.projects.active_staff_ids(project.id)
        return ProjectRead(
            id=project.id,
            name=project.name,
            client_name=project.client_name,
            data_region=project.data_region,
            required_skill_ids=project.required_skill_ids,
            starts_on=project.starts_on,
            ends_on=project.ends_on,
            status=project.status,
            staff_ids=sorted(staff, key=str),
            created_at=project.created_at,
        )

    async def visible(self, actor: Actor, project_id: UUID) -> Project:
        project = await self.projects.get(project_id)
        can_see = project is not None and (
            actor.role in _SEES_ALL
            or (
                actor.role is UserRole.PM
                and await self.projects.is_staffed(project.id, actor.user_id)
            )
        )
        if project is None or not can_see:
            raise NotFound("Project not found", code="project_not_found")
        return project

    async def read(self, actor: Actor, project_id: UUID) -> ProjectRead:
        return await self._read(await self.visible(actor, project_id))

    async def list_visible(self, actor: Actor) -> list[ProjectRead]:
        if actor.role in _SEES_ALL:
            projects = await self.projects.list_all()
        elif actor.role is UserRole.PM:
            projects = await self.projects.list_staffed_by(actor.user_id)
        else:
            raise Forbidden("Projects are visible to staff only", code="permission_denied")
        return [await self._read(p) for p in projects]

    async def set_staff(self, actor: Actor, project_id: UUID, data: StaffAssignment) -> ProjectRead:
        project = await self.visible(actor, project_id)
        # visible() already restricts PMs to projects they staff.
        if not (
            has_permission(actor.role, Permission.PROJECT_STAFF_ASSIGN) or actor.role is UserRole.PM
        ):
            raise Forbidden("Missing permission project:staff_assign", code="permission_denied")
        wanted = set(data.user_account_ids)
        if wanted - await active_pm_ids(self.session, wanted):
            raise BadRequest("Staff must be active project managers", code="staff_not_active_pm")
        rows = await self.projects.active_staff_rows(project.id)
        current = {row.user_account_id: row for row in rows}
        now = utcnow()
        for user_id, row in current.items():
            if user_id not in wanted:
                row.active_to = now
        for user_id in wanted - current.keys():
            self.projects.add_staff(
                ProjectStaff(project_id=project.id, user_account_id=user_id, active_from=now)
            )
        await self.session.flush()
        before = sorted(str(u) for u in current)
        after = sorted(str(u) for u in wanted)
        if before != after:
            await write_audit(
                self.session,
                actor=actor,
                action="project.staff_changed",
                target_type="project",
                target_id=project.id,
                before={"staff": before},
                after={"staff": after},
            )
        return await self._read(project)


async def end_staffing_for(session: AsyncSession, user_id: UUID, *, reason: str) -> None:
    """A deactivated or re-roled account stops staffing every project (spec §7.6)."""
    now = utcnow()
    for row in await ProjectRepository(session).active_rows_for_user(user_id):
        row.active_to = now
        await write_audit(
            session,
            actor=None,
            action="project.staff_removed",
            target_type="project",
            target_id=row.project_id,
            before={"staff_member": str(user_id)},
            reason=reason,
        )

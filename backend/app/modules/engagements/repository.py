from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.models import Project, ProjectStaff


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    def add(self, project: Project) -> Project:
        self.session.add(project)
        return project

    def add_staff(self, row: ProjectStaff) -> ProjectStaff:
        self.session.add(row)
        return row

    async def list_all(self) -> list[Project]:
        return list(
            (await self.session.scalars(select(Project).order_by(Project.created_at))).all()
        )

    async def list_staffed_by(self, user_id: UUID) -> list[Project]:
        stmt = (
            select(Project)
            .join(ProjectStaff, ProjectStaff.project_id == Project.id)
            .where(ProjectStaff.user_account_id == user_id, ProjectStaff.active_to.is_(None))
            .order_by(Project.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def is_staffed(self, project_id: UUID, user_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        ProjectStaff.project_id == project_id,
                        ProjectStaff.user_account_id == user_id,
                        ProjectStaff.active_to.is_(None),
                    )
                )
            )
        )

    async def active_staff_rows(self, project_id: UUID) -> list[ProjectStaff]:
        stmt = select(ProjectStaff).where(
            ProjectStaff.project_id == project_id, ProjectStaff.active_to.is_(None)
        )
        return list((await self.session.scalars(stmt)).all())

    async def active_staff_ids(self, project_id: UUID) -> set[UUID]:
        return {row.user_account_id for row in await self.active_staff_rows(project_id)}

    async def active_rows_for_user(self, user_id: UUID) -> list[ProjectStaff]:
        stmt = select(ProjectStaff).where(
            ProjectStaff.user_account_id == user_id, ProjectStaff.active_to.is_(None)
        )
        return list((await self.session.scalars(stmt)).all())

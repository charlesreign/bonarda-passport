from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.models import Engagement, Feedback, Project, ProjectStaff


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


class EngagementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, engagement_id: UUID) -> Engagement | None:
        return await self.session.get(Engagement, engagement_id)

    async def get_for_update(self, engagement_id: UUID) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(Engagement.id == engagement_id).with_for_update()
        )

    def add(self, engagement: Engagement) -> Engagement:
        self.session.add(engagement)
        return engagement

    def add_feedback(self, feedback: Feedback) -> Feedback:
        self.session.add(feedback)
        return feedback

    async def list_for_worker(self, worker_id: UUID) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(Engagement.worker_id == worker_id)
            .order_by(Engagement.start_date.desc(), Engagement.created_at.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def feedback_for(self, engagement_ids: Sequence[UUID]) -> dict[UUID, Feedback]:
        if not engagement_ids:
            return {}
        rows = await self.session.scalars(
            select(Feedback).where(Feedback.engagement_id.in_(engagement_ids))
        )
        return {f.engagement_id: f for f in rows.all()}

    async def worker_engaged_on(self, worker_id: UUID, project_ids: Sequence[UUID]) -> bool:
        if not project_ids:
            return False
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        Engagement.worker_id == worker_id,
                        Engagement.project_id.in_(project_ids),
                    )
                )
            )
        )

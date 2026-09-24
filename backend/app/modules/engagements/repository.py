from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engagements.enums import HISTORY_STATUSES, OPEN_STATUSES, EngagementStatus
from app.modules.engagements.models import Engagement, Feedback, Project, ProjectStaff
from app.modules.identity.service import active_pm_ids


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

    async def _is_active_pm(self, user_id: UUID) -> bool:
        """Staffing counts only for an active PM account. The AccessRevoked
        handler closes the staff rows of a revoked or re-roled account; this
        also covers the window before it runs (spec §7.6)."""
        return user_id in await active_pm_ids(self.session, [user_id])

    async def list_staffed_by(self, user_id: UUID) -> list[Project]:
        if not await self._is_active_pm(user_id):
            return []
        stmt = (
            select(Project)
            .join(ProjectStaff, ProjectStaff.project_id == Project.id)
            .where(ProjectStaff.user_account_id == user_id, ProjectStaff.active_to.is_(None))
            .order_by(Project.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def is_staffed(self, project_id: UUID, user_id: UUID) -> bool:
        staffed = await self.session.scalar(
            select(
                exists().where(
                    ProjectStaff.project_id == project_id,
                    ProjectStaff.user_account_id == user_id,
                    ProjectStaff.active_to.is_(None),
                )
            )
        )
        return bool(staffed) and await self._is_active_pm(user_id)

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

    async def has_history(self, worker_id: UUID) -> bool:
        """Work that has actually happened: a signed contract or later (FR-5.3)."""
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        Engagement.worker_id == worker_id,
                        Engagement.status.in_(HISTORY_STATUSES),
                    )
                )
            )
        )

    async def open_for(self, worker_id: UUID, project_id: UUID) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(
                Engagement.worker_id == worker_id,
                Engagement.project_id == project_id,
                Engagement.status.in_(OPEN_STATUSES),
            )
        )

    async def latest_for_worker(self, worker_id: UUID) -> Engagement | None:
        """The latest engagement counting as history (FR-5.3), matching
        `has_history` so prefill and reactivation agree on what "prior
        engagement" means."""
        return await self.session.scalar(
            select(Engagement)
            .where(
                Engagement.worker_id == worker_id,
                Engagement.status.in_(HISTORY_STATUSES),
            )
            .order_by(Engagement.start_date.desc(), Engagement.created_at.desc())
            .limit(1)
        )

    async def get_by_idempotency_key(self, key: str) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(Engagement.idempotency_key == key)
        )

    async def get_by_envelope_for_update(self, envelope_id: str) -> Engagement | None:
        return await self.session.scalar(
            select(Engagement).where(Engagement.esign_envelope_id == envelope_id).with_for_update()
        )

    async def due_signed(self, today: date) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(Engagement.status == EngagementStatus.SIGNED, Engagement.start_date <= today)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(stmt)).all())

    async def active_count(self, worker_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Engagement)
            .where(
                Engagement.worker_id == worker_id,
                Engagement.status == EngagementStatus.ACTIVE,
            )
        )
        return int(count or 0)

    async def stuck_candidates(
        self, *, pending_before: datetime, awaiting_before: datetime
    ) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(
                Engagement.stuck_flagged_at.is_(None),
                or_(
                    and_(
                        Engagement.status == EngagementStatus.PENDING_SIGNATURE,
                        Engagement.confirmed_at < pending_before,
                    ),
                    and_(
                        Engagement.status == EngagementStatus.AWAITING_SIGNATURE,
                        Engagement.contract_sent_at < awaiting_before,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(stmt)).all())

    async def payroll_unsignalled(self, *, billable_before: datetime) -> list[Engagement]:
        stmt = (
            select(Engagement)
            .where(
                Engagement.status.in_((EngagementStatus.ACTIVE, EngagementStatus.COMPLETED)),
                Engagement.billable_start_at < billable_before,
                Engagement.payroll_signaled_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(stmt)).all())

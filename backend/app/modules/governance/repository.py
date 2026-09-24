from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.modules.governance.enums import DisputeStatus, PolicyKind, PolicyStatus
from app.modules.governance.models import Dispute, PolicyConfig


class PolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, policy: PolicyConfig) -> PolicyConfig:
        self.session.add(policy)
        return policy

    async def list_for_kind(self, kind: PolicyKind) -> list[PolicyConfig]:
        stmt = (
            select(PolicyConfig)
            .where(PolicyConfig.kind == kind)
            .order_by(PolicyConfig.version.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_for_update(self, kind: PolicyKind, version: int) -> PolicyConfig | None:
        return await self.session.scalar(
            select(PolicyConfig)
            .where(PolicyConfig.kind == kind, PolicyConfig.version == version)
            # key_share=True takes FOR NO KEY UPDATE, not a plain FOR UPDATE: it still
            # serializes concurrent activations against each other, but does not
            # conflict with the FOR KEY SHARE lock that standing_changes inserts take
            # on policy_version_id, so activation does not block behind an
            # in-flight re-evaluation.
            .with_for_update(key_share=True)
        )

    async def active(self, kind: PolicyKind, *, for_update: bool = False) -> PolicyConfig | None:
        stmt = select(PolicyConfig).where(
            PolicyConfig.kind == kind, PolicyConfig.status == PolicyStatus.ACTIVE
        )
        if for_update:
            # See get_for_update: FOR NO KEY UPDATE avoids contending with the
            # FOR KEY SHARE lock taken by concurrent standing_changes inserts.
            stmt = stmt.with_for_update(key_share=True)
        return await self.session.scalar(stmt)

    async def next_version(self, kind: PolicyKind) -> int:
        current = await self.session.scalar(
            select(func.max(PolicyConfig.version)).where(PolicyConfig.kind == kind)
        )
        return (current or 0) + 1

    async def versions_by_id(self, ids: Sequence[UUID]) -> dict[UUID, int]:
        if not ids:
            return {}
        rows = await self.session.execute(
            select(PolicyConfig.id, PolicyConfig.version).where(PolicyConfig.id.in_(ids))
        )
        return {policy_id: version for policy_id, version in rows}


class AuditLogRepository:
    """Reads app.core's audit_log (FR-7.3). The table has no owner module;
    governance is the only reader."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def page(
        self,
        *,
        target_type: str | None,
        target_id: UUID | None,
        action: str | None,
        before_id: int | None,
        limit: int,
    ) -> list[AuditLog]:
        stmt = select(AuditLog)
        if target_type is not None:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if before_id is not None:
            stmt = stmt.where(AuditLog.id < before_id)
        stmt = stmt.order_by(AuditLog.id.desc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())


class DisputeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, dispute: Dispute) -> Dispute:
        self.session.add(dispute)
        return dispute

    async def get(self, dispute_id: UUID) -> Dispute | None:
        return await self.session.get(Dispute, dispute_id)

    async def get_for_update(self, dispute_id: UUID) -> Dispute | None:
        return await self.session.scalar(
            select(Dispute).where(Dispute.id == dispute_id).with_for_update()
        )

    async def page(
        self,
        *,
        worker_id: UUID | None,
        status: DisputeStatus | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Dispute]:
        """Oldest due first: the order People Ops work the queue in."""
        stmt = select(Dispute)
        if worker_id is not None:
            stmt = stmt.where(Dispute.worker_id == worker_id)
        if status is not None:
            stmt = stmt.where(Dispute.status == status)
        if after is not None:
            due_at, dispute_id = after
            stmt = stmt.where(
                or_(
                    Dispute.due_at > due_at,
                    and_(Dispute.due_at == due_at, Dispute.id > dispute_id),
                )
            )
        stmt = stmt.order_by(Dispute.due_at, Dispute.id).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def open_due_before(self, cutoff: datetime) -> list[Dispute]:
        stmt = (
            select(Dispute)
            .where(Dispute.status == DisputeStatus.OPEN, Dispute.due_at <= cutoff)
            .order_by(Dispute.due_at, Dispute.id)
        )
        return list((await self.session.scalars(stmt)).all())

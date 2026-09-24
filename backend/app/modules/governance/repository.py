from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.models import PolicyConfig


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

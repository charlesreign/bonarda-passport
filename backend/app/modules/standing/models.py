import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.core.time import utcnow
from app.modules.passport.service import StandingTier


class StandingChange(UUIDPrimaryKeyMixin, Base):
    """Append-only history of a worker's tier (FR-3.3, spec §6.3). A DB
    trigger rejects UPDATE and DELETE."""

    __tablename__ = "standing_changes"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    previous_tier: Mapped[StandingTier] = mapped_column(pg_enum(StandingTier), nullable=False)
    new_tier: Mapped[StandingTier] = mapped_column(pg_enum(StandingTier), nullable=False)
    contributing_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_configs.id", ondelete="RESTRICT")
    )
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="RESTRICT")
    )
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_standing_changes_worker_created", "worker_id", "created_at"),)


class SkillEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reviewer saw this worker demonstrate this skill on an engagement
    (FR-2.2). Distinct reviewers per (worker, skill) drive verification."""

    __tablename__ = "skill_evidence"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint(
            "worker_id", "skill_id", "reviewer_id", name="uq_skill_evidence_worker_skill_reviewer"
        ),
    )

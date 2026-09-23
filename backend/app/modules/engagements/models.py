import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.engagements.enums import EngagementPath, EngagementStatus, ProjectStatus, WorkMode


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(200))
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    required_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("'{}'"), nullable=False
    )
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus),
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE.value,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on", name="dates_ordered"
        ),
    )


class ProjectStaff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The data behind PM scoping (FR-9.4). Ended rows keep history."""

    __tablename__ = "project_staff"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    user_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_project_staff_active_user",
            "user_account_id",
            postgresql_where=text("active_to IS NULL"),
        ),
        Index(
            "uq_project_staff_active",
            "project_id",
            "user_account_id",
            unique=True,
            postgresql_where=text("active_to IS NULL"),
        ),
    )


class Engagement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagements"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    path: Mapped[EngagementPath] = mapped_column(pg_enum(EngagementPath), nullable=False)
    status: Mapped[EngagementStatus] = mapped_column(
        pg_enum(EngagementStatus),
        default=EngagementStatus.PENDING_SIGNATURE,
        server_default=EngagementStatus.PENDING_SIGNATURE.value,
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    work_mode: Mapped[WorkMode] = mapped_column(pg_enum(WorkMode), nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    contract_terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prefilled_from_engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contract_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billable_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payroll_signaled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stuck_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    esign_envelope_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_engagements_worker_start", "worker_id", "start_date"),
        Index("ix_engagements_project", "project_id"),
        Index(
            "ix_engagements_in_flight",
            "status",
            postgresql_where=text("status IN ('pending_signature','awaiting_signature')"),
        ),
        Index(
            "uq_engagements_open_worker_project",
            "worker_id",
            "project_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_signature','awaiting_signature','signed','active')"
            ),
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        CheckConstraint("rate > 0", name="rate_positive"),
    )


class Feedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    structured_answers: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False)
    free_text: Mapped[str | None] = mapped_column(Text)
    skill_ids_demonstrated: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("'{}'"), nullable=False
    )
    excluded_from_standing: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

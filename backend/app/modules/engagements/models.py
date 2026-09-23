import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.engagements.enums import ProjectStatus


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

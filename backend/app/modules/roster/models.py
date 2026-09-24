import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.roster.enums import FirstShotOutcome, PassReason


class RosterProfile(Base):
    """One row per worker, maintained from events and rebuilt nightly
    (spec §5.2 rule 4, §6.1). Search reads only this table."""

    __tablename__ = "roster_profiles"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    onboarding_state: Mapped[str] = mapped_column(String(20), nullable=False)
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    cross_region_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    standing_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
    verified_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
    base_location: Mapped[str | None] = mapped_column(String(120))
    availability_status: Mapped[str] = mapped_column(String(20), nullable=False)
    available_from: Mapped[date | None] = mapped_column(Date)
    engagements_total: Mapped[int] = mapped_column(Integer, nullable=False)
    engagements_last_12m: Mapped[int] = mapped_column(Integer, nullable=False)
    last_engaged_on: Mapped[date | None] = mapped_column(Date)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_roster_profiles_skill_ids", "skill_ids", postgresql_using="gin"),
        Index(
            "ix_roster_profiles_verified_skill_ids", "verified_skill_ids", postgresql_using="gin"
        ),
        Index(
            "ix_roster_profiles_region_availability",
            "data_region",
            "availability_status",
            postgresql_where=text("status IN ('active','dormant')"),
        ),
        Index("ix_roster_profiles_engagements_last_12m", "engagements_last_12m"),
        Index(
            "ix_roster_profiles_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
    )


class FirstShotReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Impression and outcome for one worker surfaced on one project's
    first-shot panel (FR-4.6, FR-4.7, NFR-5.2)."""

    __tablename__ = "first_shot_reviews"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    pm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    outcome: Mapped[FirstShotOutcome] = mapped_column(pg_enum(FirstShotOutcome), nullable=False)
    reason_code: Mapped[PassReason | None] = mapped_column(pg_enum(PassReason))

    __table_args__ = (
        UniqueConstraint("project_id", "worker_id", name="uq_first_shot_reviews_project_worker"),
        CheckConstraint(
            "(outcome = 'passed') = (reason_code IS NOT NULL)", name="reason_matches_outcome"
        ),
    )

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.passport.enums import (
    AvailabilityStatus,
    ClaimSource,
    ConsentPurpose,
    OnboardingState,
    StandingTier,
    VerificationStatus,
    WorkerStatus,
    WorkerType,
)


class Worker(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The persistent passport (FR-1.1). Never hard-deleted: erasure is
    anonymization (spec §6.3). Contact email and locale live on the worker's
    user_accounts row."""

    __tablename__ = "workers"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    worker_type: Mapped[WorkerType] = mapped_column(pg_enum(WorkerType), nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        pg_enum(WorkerStatus),
        default=WorkerStatus.DORMANT,
        server_default=WorkerStatus.DORMANT.value,
        nullable=False,
    )
    onboarding_state: Mapped[OnboardingState] = mapped_column(
        pg_enum(OnboardingState),
        default=OnboardingState.INVITED,
        server_default=OnboardingState.INVITED.value,
        nullable=False,
    )
    standing_tier: Mapped[StandingTier] = mapped_column(
        pg_enum(StandingTier),
        default=StandingTier.UNRATED,
        server_default=StandingTier.UNRATED.value,
        nullable=False,
    )
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    base_location: Mapped[str | None] = mapped_column(String(120))
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(10)), default=list, server_default=text("'{}'"), nullable=False
    )
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        pg_enum(AvailabilityStatus),
        default=AvailabilityStatus.AVAILABLE,
        server_default=AvailabilityStatus.AVAILABLE.value,
        nullable=False,
    )
    available_from: Mapped[date | None] = mapped_column(Date)
    dormant_since: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (Index("ix_workers_status_region", "status", "data_region"),)


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled taxonomy: free-text skill names cannot be searched reliably."""

    __tablename__ = "skills"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)


class SkillClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_claims"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        pg_enum(VerificationStatus),
        default=VerificationStatus.SELF_REPORTED,
        server_default=VerificationStatus.SELF_REPORTED.value,
        nullable=False,
    )
    source: Mapped[ClaimSource] = mapped_column(
        pg_enum(ClaimSource),
        default=ClaimSource.SELF,
        server_default=ClaimSource.SELF.value,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("worker_id", "skill_id", name="uq_skill_claims_worker_skill"),
        Index("ix_skill_claims_skill_id", "skill_id"),
    )


class Consent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current consent per purpose; every change is also in audit_log."""

    __tablename__ = "consents"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[ConsentPurpose] = mapped_column(pg_enum(ConsentPurpose), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(80), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("worker_id", "purpose", name="uq_consents_worker_purpose"),)

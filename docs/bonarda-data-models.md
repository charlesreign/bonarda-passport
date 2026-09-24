# Bonarda Works — Core Data Models & Database Schema (v2)

Companion to `docs/superpowers/specs/2026-09-22-bonarda-system-design-v2.md` (§6, Data strategy) and `PROJECT_STRUCTURE.md`. Defines the SQLAlchemy 2.0 async ORM layer. Each model lives in its owning module (`backend/app/modules/<module>/models.py`); shared infrastructure tables live in `backend/app/core/`.

---

## 1. Type-safety approach

1. **SQLAlchemy 2.0 `Mapped[]` / `mapped_column()` throughout** — nullability is visible to mypy.
2. **Python `Enum` classes backed by native Postgres `ENUM` types** — invalid states cannot be constructed or stored.
3. **ORM models and Pydantic schemas are separate classes** — the API contract evolves independently of table shape. Responses use one schema per visibility level (`WorkerSelf`, `WorkerDetail`, `WorkerSummary`), never one schema with optional fields.
4. **Cross-module references are plain UUID foreign keys by table name**, not ORM `relationship()` across module boundaries. Relationships are declared only within a module, so no module imports another module's models (boundary rule 1).

---

## 2. Base class and mixins

`backend/app/core/db/base.py`

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base. One metadata object for Alembic."""


class UUIDPrimaryKeyMixin:
    """Server-generated UUID keys: safe to expose, leak no ordering."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

---

## 3. Enums

`backend/app/core/enums.py`

```python
import enum


class UserRole(str, enum.Enum):
    PM = "pm"
    PEOPLE_OPS = "people_ops"
    FINANCE = "finance"
    WORKER = "worker"
    ADMIN = "admin"


class AuthProvider(str, enum.Enum):
    CORPORATE_SSO = "corporate_sso"   # FR-9.1
    MAGIC_LINK = "magic_link"         # FR-9.2


class AccountStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"               # SCIM deactivation (FR-9.12)


class WorkerType(str, enum.Enum):
    FREELANCER = "freelancer"
    CONTRACTOR = "contractor"         # employees added later without a breaking change (NFR-6.2)


class WorkerStatus(str, enum.Enum):
    ACTIVE = "active"                 # has an active engagement
    DORMANT = "dormant"               # no active engagement; still searchable (FR-9.7)
    OFFBOARDED = "offboarded"
    ANONYMIZED = "anonymized"         # erasure / retention expiry


class OnboardingState(str, enum.Enum):
    INVITED = "invited"
    PROFILE_COMPLETE = "profile_complete"


class AvailabilityStatus(str, enum.Enum):
    AVAILABLE = "available"
    AVAILABLE_FROM = "available_from"
    UNAVAILABLE = "unavailable"


class StandingTier(str, enum.Enum):
    UNRATED = "unrated"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"                 # "Trusted"


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "unverified"
    SELF_REPORTED = "self_reported"
    BONARDA_VERIFIED = "bonarda_verified"   # distinct reviewers ≥ policy threshold (FR-2.2)


class ClaimSource(str, enum.Enum):
    SELF = "self"
    EXTERNAL = "external"             # FR-2.5, post-MVA
    REVIEW = "review"


class ConsentPurpose(str, enum.Enum):
    CROSS_REGION_MATCHING = "cross_region_matching"   # NFR-4.3
    EXTERNAL_PREFILL = "external_prefill"


class ProjectStatus(str, enum.Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    CLOSED = "closed"


class EngagementPath(str, enum.Enum):
    FIRST_TIME = "first_time"         # FR-5.1
    REACTIVATION = "reactivation"     # FR-4.3


class EngagementStatus(str, enum.Enum):
    PENDING_SIGNATURE = "pending_signature"     # recorded, contract not yet dispatched
    AWAITING_SIGNATURE = "awaiting_signature"   # envelope sent
    SIGNED = "signed"                           # signed, start_date in the future
    ACTIVE = "active"                           # billable
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FirstShotOutcome(str, enum.Enum):
    SHOWN = "shown"
    SHORTLISTED = "shortlisted"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    PASSED = "passed"


class DisputeTargetType(str, enum.Enum):
    FEEDBACK = "feedback"
    STANDING_CHANGE = "standing_change"
    ENGAGEMENT = "engagement"


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"


class DisputeResolution(str, enum.Enum):
    UPHELD = "upheld"
    REJECTED = "rejected"


class PolicyKind(str, enum.Enum):
    TIERING = "tiering"
    MATCHING = "matching"
    CONCENTRATION = "concentration"
    RETENTION = "retention"


class PolicyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
```

---

## 4. `identity` module

`backend/app/modules/identity/models.py`

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import AccountStatus, AuthProvider, UserRole


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_accounts"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(nullable=False)
    auth_provider: Mapped[AuthProvider] = mapped_column(nullable=False)
    status: Mapped[AccountStatus] = mapped_column(default=AccountStatus.ACTIVE, nullable=False)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)  # staff only
    # The single link between an account and a worker (v1 had FKs both ways).
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), unique=True
    )
    can_view_governance: Mapped[bool] = mapped_column(default=False, nullable=False)  # PM leadership (FR-4.8)


class RefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rotating refresh tokens. Reuse of a rotated token revokes the family."""

    __tablename__ = "refresh_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FR-9.5 — scoped, expiring detail visibility. Reads check expires_at,
    so expiry needs no job (NFR-3.8)."""

    __tablename__ = "access_grants"

    granted_to_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    scoped_worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_access_grants_lookup",
            "granted_to_id", "scoped_worker_id", "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
```

---

## 5. `passport` module

`backend/app/modules/passport/models.py`

```python
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import (
    AvailabilityStatus, ClaimSource, ConsentPurpose, OnboardingState,
    StandingTier, VerificationStatus, WorkerStatus, WorkerType,
)


class Worker(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workers"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_type: Mapped[WorkerType] = mapped_column(nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(default=WorkerStatus.DORMANT, nullable=False)
    onboarding_state: Mapped[OnboardingState] = mapped_column(
        default=OnboardingState.INVITED, nullable=False
    )
    # Written only by the standing module's handler, via passport.service.
    standing_tier: Mapped[StandingTier] = mapped_column(default=StandingTier.UNRATED, nullable=False)
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)       # e.g. "GH", "EU"
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    base_location: Mapped[str | None] = mapped_column(String(120))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(10)), default=list, nullable=False)
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        default=AvailabilityStatus.AVAILABLE, nullable=False
    )
    available_from: Mapped[date | None] = mapped_column()
    dormant_since: Mapped[date | None] = mapped_column()

    skill_claims: Mapped[list["SkillClaim"]] = relationship(back_populates="worker")
    consents: Mapped[list["Consent"]] = relationship(back_populates="worker")


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled taxonomy — free-text skill names cannot be searched reliably."""

    __tablename__ = "skills"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)  # {"en": ..., "fr": ...}


class SkillClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_claims"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        default=VerificationStatus.SELF_REPORTED, nullable=False
    )
    source: Mapped[ClaimSource] = mapped_column(default=ClaimSource.SELF, nullable=False)

    worker: Mapped["Worker"] = relationship(back_populates="skill_claims")

    __table_args__ = (UniqueConstraint("worker_id", "skill_id", name="uq_worker_skill"),)


class Consent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current consent state per purpose; every change is also in audit_log."""

    __tablename__ = "consents"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[ConsentPurpose] = mapped_column(nullable=False)
    granted: Mapped[bool] = mapped_column(nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(80), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    worker: Mapped["Worker"] = relationship(back_populates="consents")

    __table_args__ = (UniqueConstraint("worker_id", "purpose", name="uq_worker_consent"),)
```

---

## 6. `engagements` module

`backend/app/modules/engagements/models.py`

```python
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import EngagementPath, EngagementStatus, ProjectStatus


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(200))
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    required_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, nullable=False
    )
    starts_on: Mapped[date | None] = mapped_column()
    ends_on: Mapped[date | None] = mapped_column()
    status: Mapped[ProjectStatus] = mapped_column(default=ProjectStatus.PLANNED, nullable=False)

    staff: Mapped[list["ProjectStaff"]] = relationship(back_populates="project")
    engagements: Mapped[list["Engagement"]] = relationship(back_populates="project")


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

    project: Mapped["Project"] = relationship(back_populates="staff")

    __table_args__ = (
        Index("ix_project_staff_active_user", "user_account_id",
              postgresql_where=text("active_to IS NULL")),
    )


class Engagement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "engagements"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    path: Mapped[EngagementPath] = mapped_column(nullable=False)
    status: Mapped[EngagementStatus] = mapped_column(
        default=EngagementStatus.PENDING_SIGNATURE, nullable=False
    )
    start_date: Mapped[date] = mapped_column(nullable=False)
    end_date: Mapped[date | None] = mapped_column()
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)          # ISO 4217
    work_mode: Mapped[str] = mapped_column(String(20), nullable=False)        # remote/onsite/hybrid
    location: Mapped[str | None] = mapped_column(String(120))
    contract_terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # scope, access (FR-4.4)
    prefilled_from_engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billable_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # FR-5.3
    esign_envelope_id: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    project: Mapped["Project"] = relationship(back_populates="engagements")
    feedback: Mapped["Feedback | None"] = relationship(back_populates="engagement", uselist=False)

    __table_args__ = (
        Index("ix_engagements_worker_start", "worker_id", text("start_date DESC")),
        Index("ix_engagements_project", "project_id"),
        Index("ix_engagements_in_flight", "status",
              postgresql_where=text("status IN ('pending_signature','awaiting_signature')")),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_engagement_dates"),
    )


class Feedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="RESTRICT"),
        unique=True, nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    # FR-2.3 — required keys validated by the Pydantic StructuredAnswers model.
    structured_answers: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False)
    free_text: Mapped[str | None] = mapped_column(Text)                        # FR-2.4
    skill_ids_demonstrated: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, nullable=False
    )
    # Set when a dispute against this record is upheld.
    excluded_from_standing: Mapped[bool] = mapped_column(default=False, nullable=False)

    engagement: Mapped["Engagement"] = relationship(back_populates="feedback")
```

---

## 7. `standing` module

`backend/app/modules/standing/models.py`

```python
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import StandingTier


class SkillEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per reviewer corroborating a skill (FR-2.2). Replaces the
    v1 counter, which could drift from the evidence it summarised."""

    __tablename__ = "skill_evidence"

    skill_claim_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skill_claims.id", ondelete="RESTRICT"), nullable=False
    )
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("skill_claim_id", "reviewer_id", name="uq_evidence_reviewer"),
    )


class StandingChange(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only (FR-3.3, NFR-5.1). App role has INSERT/SELECT only;
    a trigger raises on UPDATE/DELETE."""

    __tablename__ = "standing_changes"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    previous_tier: Mapped[StandingTier] = mapped_column(nullable=False)
    new_tier: Mapped[StandingTier] = mapped_column(nullable=False)
    contributing_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_configs.id", ondelete="RESTRICT"), nullable=False
    )
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(      # null = automated
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    override_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_standing_changes_worker", "worker_id", text("created_at DESC")),
        CheckConstraint(
            "actor_id IS NULL OR override_reason IS NOT NULL",
            name="ck_override_has_reason",
        ),
    )
```

---

## 8. `roster` module

`backend/app/modules/roster/models.py`

```python
import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import AvailabilityStatus, FirstShotOutcome, StandingTier, WorkerStatus


class RosterProfile(Base):
    """Read-model maintained from events + nightly rebuild. Search is a
    single-table query; roster never joins other modules' tables."""

    __tablename__ = "roster_profiles"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(nullable=False)
    onboarding_complete: Mapped[bool] = mapped_column(nullable=False)
    data_region: Mapped[str] = mapped_column(String(8), nullable=False)
    cross_region_ok: Mapped[bool] = mapped_column(nullable=False)
    standing_tier: Mapped[StandingTier] = mapped_column(nullable=False)
    skill_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False)
    verified_skill_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False)
    base_location: Mapped[str | None] = mapped_column(String(120))
    availability_status: Mapped[AvailabilityStatus] = mapped_column(nullable=False)
    available_from: Mapped[date | None] = mapped_column()
    engagements_total: Mapped[int] = mapped_column(nullable=False, default=0)
    engagements_last_12m: Mapped[int] = mapped_column(nullable=False, default=0)
    last_engaged_at: Mapped[date | None] = mapped_column()
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_roster_skills", "skill_ids", postgresql_using="gin"),
        Index("ix_roster_verified_skills", "verified_skill_ids", postgresql_using="gin"),
        Index("ix_roster_region_avail", "data_region", "availability_status",
              postgresql_where=text("status IN ('active','dormant')")),
        Index("ix_roster_name_trgm", "display_name", postgresql_using="gin",
              postgresql_ops={"display_name": "gin_trgm_ops"}),
        Index("ix_roster_underused", "engagements_last_12m"),
    )


class FirstShotReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FR-4.7 — one row per (project, worker) surfaced in the panel."""

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
    outcome: Mapped[FirstShotOutcome] = mapped_column(default=FirstShotOutcome.SHOWN, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40))

    __table_args__ = (UniqueConstraint("project_id", "worker_id", name="uq_first_shot_project_worker"),)
```

---

## 9. `governance` module

`backend/app/modules/governance/models.py`

```python
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.enums import (
    DisputeResolution, DisputeStatus, DisputeTargetType, PolicyKind, PolicyStatus,
)


class Dispute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "disputes"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    # Polymorphic target made explicit; the service verifies the target
    # exists and belongs to worker_id before insert.
    target_type: Mapped[DisputeTargetType] = mapped_column(nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(default=DisputeStatus.OPEN, nullable=False)
    resolution: Mapped[DisputeResolution | None] = mapped_column()
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolver_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # NFR-4.2 SLA

    __table_args__ = (
        Index("ix_disputes_queue", "status", "due_at"),
        CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL)",
            name="ck_dispute_resolution_matches_status",
        ),
    )


class PolicyConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Versioned rules (NFR-5.1, NFR-9.2). `rules` is validated against a
    Pydantic schema per kind before insert. Two-person activation."""

    __tablename__ = "policy_configs"

    kind: Mapped[PolicyKind] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[PolicyStatus] = mapped_column(default=PolicyStatus.DRAFT, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    activated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_policy_kind_version"),
        Index("uq_policy_one_active", "kind", unique=True,
              postgresql_where=text("status = 'active'")),
        CheckConstraint(
            "activated_by_id IS NULL OR created_by_id IS NULL OR activated_by_id <> created_by_id",
            name="ck_policy_two_person",
        ),
    )


class ConcentrationRollup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "concentration_rollups"

    period_start: Mapped[date] = mapped_column(nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)          # "org" or a region code
    engagements_total: Mapped[int] = mapped_column(nullable=False)
    engagements_repeat_3plus: Mapped[int] = mapped_column(nullable=False)
    share: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    first_shot_shown: Mapped[int] = mapped_column(nullable=False)
    first_shot_engaged: Mapped[int] = mapped_column(nullable=False)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_configs.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (UniqueConstraint("period_start", "scope", name="uq_rollup_period_scope"),)
```

---

## 10. Core infrastructure tables

`backend/app/core/audit/models.py`, `backend/app/core/outbox/models.py`

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class AuditLog(Base):
    """Append-only (FR-7.3, FR-9.13, NFR-3.3). Written by AuditWriter on the
    same session as the domain change. No FKs: audit must outlive targets."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), nullable=False)        # e.g. "engagement.reactivated"
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_audit_target", "target_type", "target_id", text("occurred_at DESC")),
        Index("ix_audit_time_brin", "occurred_at", postgresql_using="brin"),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), server_default=func.gen_random_uuid(), unique=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)

    __table_args__ = (
        Index("ix_outbox_pending", "id", postgresql_where=text("dispatched_at IS NULL")),
    )


class ProcessedEvent(Base):
    """Handler-level dedupe: a handler inserts (event_id, handler) in its own
    transaction and skips if the row already exists."""

    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    handler: Mapped[str] = mapped_column(String(80), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Append-only enforcement (in the first Alembic migration):

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
  -- Only the retention role may delete, and only from audit_log.
  IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'audit_log' AND current_user = 'bonarda_retention' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER standing_changes_append_only BEFORE UPDATE OR DELETE ON standing_changes
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

REVOKE UPDATE, DELETE ON audit_log, standing_changes FROM bonarda_app;
```

The retention job deletes expired `audit_log` rows (older than the retention policy's 7 years) by connecting as the separate `bonarda_retention` role, which the trigger allows to `DELETE` from `audit_log` only. This is the single path that can remove audit rows; each run writes its own summary audit entry.

---

## 11. Writing a change: audit + outbox in one transaction

`backend/app/modules/engagements/service.py` (excerpt)

```python
class EngagementService:
    def __init__(self, session: AsyncSession, repo: EngagementRepository,
                 audit: AuditWriter, outbox: OutboxWriter) -> None:
        self.session, self.repo, self.audit, self.outbox = session, repo, audit, outbox

    async def reactivate(self, cmd: ReactivationCreate, actor: Actor, idem_key: str) -> Engagement:
        if existing := await self.repo.get_by_idempotency_key(idem_key):
            return existing
        engagement = await self.repo.create(Engagement(
            worker_id=cmd.worker_id, project_id=cmd.project_id,
            path=EngagementPath.REACTIVATION, confirmed_at=utcnow(),
            idempotency_key=idem_key, created_by_id=actor.user_id, **cmd.terms(),
        ))
        await self.audit.record(self.session, actor, "engagement.reactivated",
                                target=engagement, after=EngagementRead.model_validate(engagement))
        await self.outbox.emit(self.session, EngagementCreated(engagement_id=engagement.id,
                                                               worker_id=engagement.worker_id))
        return engagement  # the request-scoped session commits all three together
```

---

## 12. Pydantic schemas — one per visibility level

`backend/app/modules/passport/schemas.py`

```python
class WorkerSummary(BaseModel):
    """Search-card level: PM within a staffed project's scope."""
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    display_name: str
    standing_tier: StandingTier
    verified_skill_ids: list[uuid.UUID]
    skill_ids: list[uuid.UUID]
    base_location: str | None
    availability_status: AvailabilityStatus
    available_from: date | None
    engagements_total: int


class WorkerDetail(WorkerSummary):
    """Relationship, grant or People Ops level."""
    engagements: list[EngagementRead]
    feedback: list[FeedbackRead]
    standing_explanation: StandingExplanation
    open_disputes: int
    last_reactivation_days_to_start: float | None  # FR-4.2


class WorkerSelf(WorkerDetail):
    """The worker viewing their own passport."""
    email: EmailStr
    languages: list[str]
    locale: str
    consents: list[ConsentRead]
    disputes: list[DisputeRead]


class WorkerUpdate(BaseModel):
    """FR-1.5 — self-editable fields only."""
    base_location: str | None = None
    languages: list[str] | None = None
    locale: Literal["en", "fr"] | None = None
    availability_status: AvailabilityStatus | None = None
    available_from: date | None = None
```

`backend/app/modules/engagements/schemas.py`

```python
class StructuredAnswers(BaseModel):
    """FR-2.3 — all required; a missing key is a 422."""
    model_config = ConfigDict(extra="forbid")
    delivered_on_agreed_dates: bool
    handled_scope_changes_without_escalation: bool
    would_reengage: bool


class FeedbackCreate(BaseModel):
    structured_answers: StructuredAnswers
    free_text: str | None = Field(default=None, max_length=2000)
    skill_ids_demonstrated: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    # reviewer_id is taken from the authenticated actor, never from the body.
```

---

## 13. Constraints and referential rules summary

| Table | Constraint / index | Purpose |
|---|---|---|
| `user_accounts` | `UNIQUE (email)`, `UNIQUE (oidc_subject)`, `UNIQUE (worker_id)` | One account per person; single worker link |
| `workers` | Never hard-deleted; `status=anonymized` for erasure | Preserves structural history for metrics |
| `skill_claims` | `UNIQUE (worker_id, skill_id)` | One claim per skill |
| `consents` | `UNIQUE (worker_id, purpose)` | One current state per purpose |
| `engagements` | `UNIQUE (idempotency_key)`; `CHECK end_date >= start_date`; in-flight partial index | Idempotent reactivation; stuck detector |
| `feedback` | `UNIQUE (engagement_id)` | One review per engagement |
| `skill_evidence` | `UNIQUE (skill_claim_id, reviewer_id)` | Distinct reviewers really are distinct (FR-2.2) |
| `standing_changes` | Append-only trigger; `CHECK actor_id IS NULL OR override_reason IS NOT NULL` | NFR-5.1 |
| `first_shot_reviews` | `UNIQUE (project_id, worker_id)` | One row per surfaced candidate per project |
| `disputes` | `CHECK` resolution present iff resolved | Consistent state |
| `policy_configs` | `UNIQUE (kind, version)`; partial unique active per kind; two-person `CHECK` | NFR-5.1, NFR-9.2 |
| `audit_log` | Append-only trigger; no FKs | Audit outlives its targets |
| `outbox_events` | `UNIQUE (event_id)`; pending partial index | Relay claim |
| `processed_events` | PK `(event_id, handler)` | Exactly-once handler effects |

**`ondelete` policy:** `RESTRICT` for anything history-bearing that points at `workers`, `projects`, `engagements`, `skill_claims` or `policy_configs`; `SET NULL` for informational actor references (`reviewer_id`, `granted_by_id`, `actor_id`, `created_by_id`); `CASCADE` only for data that is meaningless without its parent and carries no history (`refresh_sessions`, `consents` — consent changes are also in `audit_log`, `roster_profiles`).

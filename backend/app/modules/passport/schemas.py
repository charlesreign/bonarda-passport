from datetime import date, datetime
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.i18n import Locale
from app.core.outbox.events import DomainEvent
from app.modules.passport.enums import (
    AvailabilityStatus,
    ConsentPurpose,
    OnboardingState,
    StandingTier,
    VerificationStatus,
    WorkerStatus,
    WorkerType,
)


class SkillCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    name_i18n: dict[Locale, str]

    @field_validator("name_i18n")
    @classmethod
    def _english_name_required(cls, value: dict[Locale, str]) -> dict[Locale, str]:
        if "en" not in value:
            raise ValueError("an English name is required")
        if any(not name.strip() or len(name) > 120 for name in value.values()):
            raise ValueError("names must be 1-120 characters")
        return value


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name_i18n: dict[str, str]


class SkillClaimCreate(BaseModel):
    skill_id: UUID


class WorkerSkill(BaseModel):
    skill_id: UUID
    slug: str
    verification_status: VerificationStatus


class WorkerUpdated(DomainEvent):
    event_type: ClassVar[str] = "passport.worker_updated"
    fields: list[str]


class WorkerRegion(BaseModel):
    data_region: str
    cross_region_ok: bool


LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]


class _SummaryFields(BaseModel):
    id: UUID
    full_name: str
    worker_type: WorkerType
    status: WorkerStatus
    data_region: str
    base_location: str | None
    availability_status: AvailabilityStatus
    available_from: date | None
    standing_tier: StandingTier
    skills: list[WorkerSkill]


class _DetailFields(_SummaryFields):
    languages: list[str]
    onboarding_state: OnboardingState
    dormant_since: date | None
    created_at: datetime


class WorkerSummary(_SummaryFields):
    view: Literal["summary"] = "summary"


class WorkerDetail(_DetailFields):
    view: Literal["detail"] = "detail"


class WorkerSelf(_DetailFields):
    view: Literal["self"] = "self"
    email: str
    locale: str


WorkerView = Annotated[WorkerSummary | WorkerDetail | WorkerSelf, Field(discriminator="view")]

_REQUIRED_WHEN_SET = ("full_name", "languages", "availability_status")


class WorkerUpdate(BaseModel):
    """Self-editable fields only (FR-1.5). Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_location: str | None = Field(default=None, max_length=120)
    languages: list[LanguageCode] | None = Field(default=None, max_length=10)
    availability_status: AvailabilityStatus | None = None
    available_from: date | None = None

    @field_validator("languages")
    @classmethod
    def _dedupe(cls, value: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(value)) if value is not None else None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for field in _REQUIRED_WHEN_SET:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be cleared")
        wants_date = self.availability_status is AvailabilityStatus.AVAILABLE_FROM
        if wants_date and self.available_from is None:
            raise ValueError("available_from is required with availability_status=available_from")
        if self.available_from is not None and not wants_date:
            raise ValueError("available_from needs availability_status=available_from")
        return self


class ConsentRead(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    legal_basis: str | None
    granted_at: datetime | None
    withdrawn_at: datetime | None


class ConsentUpdate(BaseModel):
    granted: bool


class ConsentChanged(DomainEvent):
    event_type: ClassVar[str] = "passport.consent_changed"
    purpose: ConsentPurpose
    granted: bool


class InvitationCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    worker_type: WorkerType
    data_region: str = Field(pattern=r"^[A-Z]{2,8}$")
    locale: Locale = "en"


class InvitationRead(BaseModel):
    worker_id: UUID
    email: str
    onboarding_state: OnboardingState
    resent: bool = False


class WorkerInvited(DomainEvent):
    event_type: ClassVar[str] = "passport.worker_invited"
    invited_by_id: UUID

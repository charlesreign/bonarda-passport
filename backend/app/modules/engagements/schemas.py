from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.outbox.events import DomainEvent
from app.modules.engagements.enums import EngagementPath, EngagementStatus, ProjectStatus, WorkMode
from app.modules.engagements.models import Engagement, Feedback


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    data_region: str = Field(pattern=r"^[A-Z]{2,8}$")
    required_skill_ids: list[UUID] = Field(default_factory=list, max_length=50)
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must not be before starts_on")
        return self


class ProjectRead(BaseModel):
    id: UUID
    name: str
    client_name: str | None
    data_region: str
    required_skill_ids: list[UUID]
    starts_on: date | None
    ends_on: date | None
    status: ProjectStatus
    staff_ids: list[UUID]
    created_at: datetime


class StaffAssignment(BaseModel):
    user_account_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("user_account_ids")
    @classmethod
    def _dedupe(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class ContractTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(min_length=1, max_length=2000)
    access_notes: str | None = Field(default=None, max_length=2000)


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    structured_answers: dict[str, bool]
    free_text: str | None
    skill_ids_demonstrated: list[UUID]
    reviewer_id: UUID | None
    created_at: datetime


class EngagementRead(BaseModel):
    id: UUID
    worker_id: UUID
    project_id: UUID
    path: EngagementPath
    status: EngagementStatus
    start_date: date
    end_date: date | None
    rate: Decimal
    currency: str
    work_mode: WorkMode
    location: str | None
    contract_terms: ContractTerms
    prefilled_from_engagement_id: UUID | None
    confirmed_at: datetime
    contract_sent_at: datetime | None
    signed_at: datetime | None
    billable_start_at: datetime | None
    completed_at: datetime | None
    stuck: bool
    feedback: FeedbackRead | None


class EngagementCreate(BaseModel):
    """Terms a PM confirms (FR-4.3/4.4). Workers are addressed in the path."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    start_date: date
    end_date: date | None = None
    rate: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    work_mode: WorkMode
    location: str | None = Field(default=None, max_length=120)
    contract_terms: ContractTerms

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class ReactivationPrefill(BaseModel):
    """Contract terms from the most recent engagement (FR-4.4). No history,
    no feedback: prefill needs only summary visibility."""

    prefilled_from_engagement_id: UUID
    rate: Decimal
    currency: str
    work_mode: WorkMode
    location: str | None
    contract_terms: ContractTerms
    last_days_to_start: float | None


class ReactivationCreate(EngagementCreate):
    prefilled_from_engagement_id: UUID | None = None


class EngagementCreated(DomainEvent):
    event_type: ClassVar[str] = "engagements.engagement_created"
    worker_id: UUID
    project_id: UUID
    path: EngagementPath


def engagement_read(engagement: Engagement, feedback: Feedback | None) -> EngagementRead:
    return EngagementRead(
        id=engagement.id,
        worker_id=engagement.worker_id,
        project_id=engagement.project_id,
        path=engagement.path,
        status=engagement.status,
        start_date=engagement.start_date,
        end_date=engagement.end_date,
        rate=engagement.rate,
        currency=engagement.currency,
        work_mode=engagement.work_mode,
        location=engagement.location,
        contract_terms=ContractTerms.model_validate(engagement.contract_terms),
        prefilled_from_engagement_id=engagement.prefilled_from_engagement_id,
        confirmed_at=engagement.confirmed_at,
        contract_sent_at=engagement.contract_sent_at,
        signed_at=engagement.signed_at,
        billable_start_at=engagement.billable_start_at,
        completed_at=engagement.completed_at,
        stuck=engagement.stuck_flagged_at is not None,
        feedback=FeedbackRead.model_validate(feedback) if feedback is not None else None,
    )

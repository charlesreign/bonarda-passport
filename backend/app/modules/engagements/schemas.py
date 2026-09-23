from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.engagements.enums import ProjectStatus


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

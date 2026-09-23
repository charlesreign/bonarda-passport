from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.i18n import Locale
from app.core.outbox.events import DomainEvent
from app.modules.passport.enums import VerificationStatus


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

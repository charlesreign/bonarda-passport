from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import UserRole
from app.core.outbox.events import DomainEvent


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
    worker_id: UUID | None
    can_view_governance: bool


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkVerify(BaseModel):
    token: str


class GrantCreate(BaseModel):
    granted_to_id: UUID
    scoped_worker_id: UUID
    reason: str = Field(min_length=10, max_length=500)
    expires_at: AwareDatetime


class GrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    granted_to_id: UUID
    scoped_worker_id: UUID
    granted_by_id: UUID | None
    reason: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class GrantCreated(DomainEvent):
    event_type: ClassVar[str] = "identity.grant_created"
    granted_to_id: UUID
    scoped_worker_id: UUID
    expires_at: datetime

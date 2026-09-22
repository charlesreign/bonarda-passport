from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import UserRole


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

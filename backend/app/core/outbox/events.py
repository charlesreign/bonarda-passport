from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DomainEvent(BaseModel):
    """Base for events published through the outbox. Subclasses set a unique
    `event_type` like "engagements.engagement_created" and add payload fields."""

    model_config = ConfigDict(frozen=True)

    event_type: ClassVar[str]
    aggregate_id: UUID

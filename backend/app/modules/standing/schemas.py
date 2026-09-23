from typing import ClassVar
from uuid import UUID

from app.core.outbox.events import DomainEvent
from app.modules.passport.service import StandingTier


class StandingChanged(DomainEvent):
    """aggregate_id is the worker."""

    event_type: ClassVar[str] = "standing.standing_changed"
    previous_tier: StandingTier
    new_tier: StandingTier
    policy_version: int | None


class SkillVerified(DomainEvent):
    """aggregate_id is the worker."""

    event_type: ClassVar[str] = "standing.skill_verified"
    skill_id: UUID

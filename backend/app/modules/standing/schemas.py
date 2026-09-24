from datetime import date, datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel

from app.core.outbox.events import DomainEvent
from app.modules.governance.schemas import TierRule
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


class StandingFactors(BaseModel):
    completed: int
    distinct_reviewers: int
    positive_ratio: float
    window_start: date


class StandingChangeRead(BaseModel):
    previous_tier: StandingTier
    new_tier: StandingTier
    factors: dict[str, Any]
    policy_version: int | None
    automated: bool
    override_reason: str | None
    occurred_at: datetime


class StandingExplanation(BaseModel):
    """Tier, signals and policy version (spec §2.1 #2, FR-1.3)."""

    worker_id: UUID
    tier: StandingTier
    # The tier the active policy gives today; differs from `tier` until the
    # recalculation handler or the nightly run records the change.
    evaluated_tier: StandingTier
    policy_version: int
    window_months: int
    tiers: list[TierRule]
    factors: StandingFactors
    history: list[StandingChangeRead]

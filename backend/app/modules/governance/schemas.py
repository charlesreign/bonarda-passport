from datetime import datetime
from typing import Any, ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.outbox.events import DomainEvent
from app.modules.governance.enums import (
    DisputeResolution,
    DisputeStatus,
    DisputeTargetType,
    PolicyKind,
    PolicyStatus,
)

# Tier names are strings here so governance stays independent of passport;
# they match passport's StandingTier values.
TierName = Literal["tier_1", "tier_2"]
_TIER_RANK = {"tier_1": 1, "tier_2": 2}


class TierRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: TierName
    min_completed: int = Field(ge=0, le=1000)
    min_distinct_reviewers: int = Field(ge=0, le=1000)
    min_positive_ratio: float = Field(ge=0, le=1)


class SkillVerificationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_distinct_reviewers: int = Field(ge=1, le=20)


class TieringRules(BaseModel):
    """Spec §7.3. The engine awards the first tier whose thresholds are all met,
    so tiers must be listed highest first."""

    model_config = ConfigDict(extra="forbid")

    window_months: int = Field(ge=1, le=120)
    tiers: list[TierRule] = Field(min_length=1, max_length=5)
    default: Literal["unrated"]
    skill_verification: SkillVerificationRule

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        ranks = [_TIER_RANK[t.tier] for t in self.tiers]
        if len(set(ranks)) != len(ranks):
            raise ValueError("each tier may appear once")
        if ranks != sorted(ranks, reverse=True):
            raise ValueError("tiers must be listed highest first")
        return self


class MatchingWeights(BaseModel):
    """Spec §7.4. Selection frequency and engagement count have no field: they
    cannot be weighted (FR-6.2)."""

    model_config = ConfigDict(extra="forbid")

    verified_skills: float = Field(ge=0, le=1)
    self_reported_skills: float = Field(ge=0, le=1)
    availability: float = Field(ge=0, le=1)
    tier: float = Field(ge=0, le=0.15)  # FR-3.4: tier is capped at 15% of the score

    @model_validator(mode="after")
    def _sums_to_one(self) -> Self:
        total = self.verified_skills + self.self_reported_skills + self.availability + self.tier
        if abs(total - 1) > 1e-6:
            raise ValueError("weights must sum to 1")
        return self


class FirstShotRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_size: int = Field(ge=1, le=20)
    underused_max_engagements_12m: int = Field(ge=0, le=50)
    exclude_top_candidates: int = Field(ge=0, le=100)


class MatchingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: MatchingWeights
    tier_weights: dict[Literal["unrated", "tier_1", "tier_2"], float]
    availability_near_days: int = Field(ge=0, le=90)
    first_shot: FirstShotRules

    @model_validator(mode="after")
    def _all_tiers_weighted(self) -> Self:
        if set(self.tier_weights) != {"unrated", "tier_1", "tier_2"}:
            raise ValueError("tier_weights must give a weight for unrated, tier_1 and tier_2")
        if any(not 0 <= w <= 1 for w in self.tier_weights.values()):
            raise ValueError("tier_weights must be between 0 and 1")
        return self


RULES_BY_KIND: dict[PolicyKind, type[BaseModel]] = {
    PolicyKind.TIERING: TieringRules,
    PolicyKind.MATCHING: MatchingRules,
}


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, Any]
    notes: str | None = Field(default=None, max_length=500)


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: PolicyKind
    version: int
    status: PolicyStatus
    rules: dict[str, Any]
    notes: str | None
    created_by_id: UUID | None
    activated_by_id: UUID | None
    activated_at: datetime | None
    created_at: datetime


class TieringPolicy(BaseModel):
    id: UUID
    version: int
    rules: TieringRules


class MatchingPolicy(BaseModel):
    id: UUID
    version: int
    rules: MatchingRules


class PolicyActivated(DomainEvent):
    """aggregate_id is the policy_configs row."""

    event_type: ClassVar[str] = "governance.policy_activated"
    kind: PolicyKind
    version: int
    previous_version: int | None


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_role: str | None
    action: str
    target_type: str
    target_id: UUID
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    correlation_id: str | None


class AuditLogPage(BaseModel):
    items: list[AuditEntryRead]
    next_cursor: str | None


class DisputeCreate(BaseModel):
    """The worker is the caller; a body never names a worker (spec §7.1)."""

    model_config = ConfigDict(extra="forbid")

    target_type: DisputeTargetType
    target_id: UUID
    reason: str = Field(min_length=10, max_length=2000)


class DisputeResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: DisputeResolution
    resolution_notes: str = Field(min_length=10, max_length=2000)


class DisputeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    worker_id: UUID
    target_type: DisputeTargetType
    target_id: UUID
    reason: str
    status: DisputeStatus
    resolution: DisputeResolution | None
    resolution_notes: str | None
    resolver_id: UUID | None
    resolved_at: datetime | None
    due_at: datetime
    created_at: datetime


class DisputePage(BaseModel):
    items: list[DisputeRead]
    next_cursor: str | None


class DisputeFiled(DomainEvent):
    """aggregate_id is the dispute. No reason text: it is personal data."""

    event_type: ClassVar[str] = "governance.dispute_filed"
    worker_id: UUID
    target_type: DisputeTargetType
    target_id: UUID


class DisputeResolved(DomainEvent):
    """aggregate_id is the dispute. No notes text: handlers read the row."""

    event_type: ClassVar[str] = "governance.dispute_resolved"
    worker_id: UUID
    target_type: DisputeTargetType
    target_id: UUID
    resolution: DisputeResolution

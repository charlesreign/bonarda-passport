from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.modules.roster.enums import FirstShotOutcome, PassReason


class ScoreComponent(BaseModel):
    weight: float
    value: float
    points: float


class ScoreBreakdown(BaseModel):
    """Every candidate carries how its score was made (spec §7.4)."""

    verified_skills: ScoreComponent
    self_reported_skills: ScoreComponent
    availability: ScoreComponent
    tier: ScoreComponent
    total: float
    policy_version: int


class CandidateCard(BaseModel):
    """Summary level only (spec §7.1): no history, feedback or contact data."""

    worker_id: UUID
    display_name: str
    standing_tier: str
    verified_skill_ids: list[UUID]
    self_reported_skill_ids: list[UUID]
    availability_status: str
    available_from: date | None
    base_location: str | None
    engagements_total: int


class Candidate(BaseModel):
    worker: CandidateCard
    score: float
    score_breakdown: ScoreBreakdown


class CandidatePage(BaseModel):
    items: list[Candidate]
    next_cursor: str | None


class FirstShotItem(BaseModel):
    worker: CandidateCard
    outcome: FirstShotOutcome
    reason_code: PassReason | None


class FirstShotPanel(BaseModel):
    """The mandatory first-shot resource (FR-4.6): shown on the same page as
    candidates, never hideable."""

    project_id: UUID
    policy_version: int
    items: list[FirstShotItem]

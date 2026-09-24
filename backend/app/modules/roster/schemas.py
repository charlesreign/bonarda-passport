from pydantic import BaseModel


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

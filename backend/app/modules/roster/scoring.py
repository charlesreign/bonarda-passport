"""Candidate scoring (spec §7.4, FR-3.4, FR-6.1, FR-6.2): pure functions over
roster rows and the active matching policy. Engagement count and selection
history are not inputs, so they cannot influence the score."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, cast
from uuid import UUID

from app.modules.governance.schemas import MatchingPolicy
from app.modules.roster.models import RosterProfile
from app.modules.roster.schemas import ScoreBreakdown, ScoreComponent


@dataclass(frozen=True, slots=True)
class ProjectNeeds:
    required_skill_ids: frozenset[UUID]
    starts_on: date


def availability_fit(
    status: str, available_from: date | None, starts_on: date, near_days: int
) -> float:
    if status == "available":
        return 1.0
    if status == "available_from" and available_from is not None:
        if available_from <= starts_on:
            return 1.0
        if available_from <= starts_on + timedelta(days=near_days):
            return 0.5
    return 0.0


def _component(weight: float, value: float) -> ScoreComponent:
    return ScoreComponent(weight=weight, value=round(value, 4), points=round(weight * value, 4))


def score(profile: RosterProfile, needs: ProjectNeeds, policy: MatchingPolicy) -> ScoreBreakdown:
    rules = policy.rules
    required = needs.required_skill_ids
    verified = set(profile.verified_skill_ids)
    self_reported = set(profile.skill_ids) - verified
    verified_value = len(required & verified) / len(required) if required else 0.0
    self_value = len(required & self_reported) / len(required) if required else 0.0
    fit = availability_fit(
        profile.availability_status,
        profile.available_from,
        needs.starts_on,
        rules.availability_near_days,
    )
    tier = cast("Literal['unrated', 'tier_1', 'tier_2']", profile.standing_tier)
    parts = {
        "verified_skills": _component(rules.weights.verified_skills, verified_value),
        "self_reported_skills": _component(rules.weights.self_reported_skills, self_value),
        "availability": _component(rules.weights.availability, fit),
        "tier": _component(rules.weights.tier, rules.tier_weights[tier]),
    }
    return ScoreBreakdown(
        **parts,
        total=round(sum(c.points for c in parts.values()), 4),
        policy_version=policy.version,
    )


def rank(
    profiles: Iterable[RosterProfile], needs: ProjectNeeds, policy: MatchingPolicy
) -> list[tuple[ScoreBreakdown, RosterProfile]]:
    scored = [(score(p, needs, policy), p) for p in profiles]
    return sorted(scored, key=lambda sp: (-sp[0].total, str(sp[1].worker_id)))

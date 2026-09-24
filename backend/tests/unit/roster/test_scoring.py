from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.governance.schemas import MatchingPolicy, MatchingRules
from app.modules.roster.models import RosterProfile
from app.modules.roster.scoring import ProjectNeeds, availability_fit, rank, score
from tests.support import _seed_policy_rows

START = date(2026, 10, 1)
POLICY = MatchingPolicy(
    id=uuid4(),
    version=1,
    rules=MatchingRules.model_validate(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    ),
)


def _profile(
    *,
    claimed: list[UUID] | None = None,
    verified: list[UUID] | None = None,
    tier: str = "unrated",
    availability: str = "available",
    available_from: date | None = None,
    engagements_last_12m: int = 0,
) -> RosterProfile:
    return RosterProfile(
        worker_id=uuid4(),
        display_name="Test",
        status="dormant",
        onboarding_state="profile_complete",
        data_region="GH",
        cross_region_ok=False,
        standing_tier=tier,
        skill_ids=list(claimed or []),
        verified_skill_ids=list(verified or []),
        base_location="Accra",
        availability_status=availability,
        available_from=available_from,
        engagements_total=engagements_last_12m,
        engagements_last_12m=engagements_last_12m,
        last_engaged_on=None,
        refreshed_at=None,
    )


@pytest.mark.parametrize(
    ("status", "available_from", "fit"),
    [
        ("available", None, 1.0),
        ("available_from", START, 1.0),
        ("available_from", START + timedelta(days=14), 0.5),
        ("available_from", START + timedelta(days=15), 0.0),
        ("available_from", None, 0.0),
        ("unavailable", None, 0.0),
    ],
)
def test_availability_fit(status: str, available_from: date | None, fit: float) -> None:
    assert availability_fit(status, available_from, START, 14) == fit


def test_verified_and_self_reported_coverage_are_weighted_separately() -> None:
    a, b = uuid4(), uuid4()
    needs = ProjectNeeds(required_skill_ids=frozenset({a, b}), starts_on=START)

    breakdown = score(_profile(claimed=[a, b], verified=[a]), needs, POLICY)

    assert (breakdown.verified_skills.value, breakdown.verified_skills.points) == (0.5, 0.25)
    assert (breakdown.self_reported_skills.value, breakdown.self_reported_skills.points) == (
        0.5,
        0.1,
    )
    assert breakdown.availability.points == 0.15
    assert breakdown.tier.points == 0.0
    assert breakdown.total == 0.5
    assert breakdown.policy_version == 1


def test_tier_cannot_outweigh_verified_skills() -> None:
    skill = uuid4()
    needs = ProjectNeeds(required_skill_ids=frozenset({skill}), starts_on=START)
    verified_unrated = _profile(claimed=[skill], verified=[skill])
    self_reported_trusted = _profile(claimed=[skill], tier="tier_2")

    ranked = rank([self_reported_trusted, verified_unrated], needs, POLICY)

    assert ranked[0][1] is verified_unrated
    assert ranked[0][0].total == 0.65
    assert ranked[1][0].total == 0.5


def test_engagement_count_has_no_weight() -> None:
    skill = uuid4()
    needs = ProjectNeeds(required_skill_ids=frozenset({skill}), starts_on=START)

    busy = score(_profile(claimed=[skill], engagements_last_12m=9), needs, POLICY)
    idle = score(_profile(claimed=[skill], engagements_last_12m=0), needs, POLICY)

    assert busy.total == idle.total


def test_a_project_without_required_skills_scores_availability_and_tier_only() -> None:
    needs = ProjectNeeds(required_skill_ids=frozenset(), starts_on=START)

    breakdown = score(_profile(tier="tier_1"), needs, POLICY)

    assert (breakdown.verified_skills.value, breakdown.self_reported_skills.value) == (0.0, 0.0)
    assert breakdown.total == 0.225


def test_ranking_ties_break_on_worker_id() -> None:
    needs = ProjectNeeds(required_skill_ids=frozenset(), starts_on=START)
    profiles = [_profile(), _profile(), _profile()]

    ranked = rank(profiles, needs, POLICY)

    assert [p.worker_id for _, p in ranked] == sorted((p.worker_id for p in profiles), key=str)

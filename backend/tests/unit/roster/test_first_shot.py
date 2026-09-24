from datetime import date
from uuid import UUID, uuid4

from app.modules.governance.schemas import MatchingRules
from app.modules.roster.first_shot import select_panel
from app.modules.roster.models import RosterProfile
from app.modules.roster.scoring import ProjectNeeds
from tests.support import _seed_policy_rows

RULES = MatchingRules.model_validate(
    next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
)
SKILL = uuid4()
NEEDS = ProjectNeeds(required_skill_ids=frozenset({SKILL}), starts_on=date(2026, 10, 1))


def _profile(
    *,
    claimed: bool = True,
    verified: bool = False,
    tier: str = "unrated",
    last_12m: int = 0,
    availability: str = "available",
) -> RosterProfile:
    return RosterProfile(
        worker_id=uuid4(),
        display_name="Test",
        status="dormant",
        onboarding_state="profile_complete",
        data_region="GH",
        cross_region_ok=False,
        standing_tier=tier,
        skill_ids=[SKILL] if claimed else [],
        verified_skill_ids=[SKILL] if verified else [],
        base_location=None,
        availability_status=availability,
        available_from=None,
        engagements_total=last_12m,
        engagements_last_12m=last_12m,
        last_engaged_on=None,
        refreshed_at=None,
    )


def _panel(
    profiles: list[RosterProfile],
    exclude: set[UUID] | None = None,
    project: UUID | None = None,
) -> list[RosterProfile]:
    return select_panel(
        profiles,
        project_id=project or UUID(int=1),
        needs=NEEDS,
        rules=RULES,
        exclude=exclude or set(),
    )


def test_only_qualified_available_underused_workers_are_eligible() -> None:
    ok = _profile()
    missing_skill = _profile(claimed=False)
    unavailable = _profile(availability="unavailable")
    busy = _profile(last_12m=2)

    assert _panel([ok, missing_skill, unavailable, busy]) == [ok]


def test_tier_never_filters_the_pool() -> None:
    unrated, trusted = _profile(tier="unrated"), _profile(tier="tier_2")

    assert set(p.worker_id for p in _panel([unrated, trusted])) == {
        unrated.worker_id,
        trusted.worker_id,
    }


def test_ranking_is_coverage_then_least_engaged() -> None:
    verified = _profile(verified=True, last_12m=1)
    fresh = _profile(last_12m=0)
    once = _profile(last_12m=1)

    assert _panel([once, fresh, verified]) == [verified, fresh, once]


def test_excluded_workers_and_panel_size() -> None:
    profiles = [_profile() for _ in range(8)]
    excluded = {profiles[0].worker_id}

    panel = _panel(profiles, exclude=excluded)

    assert len(panel) == RULES.first_shot.panel_size
    assert profiles[0] not in panel


def test_rotation_is_stable_per_project_and_differs_across_projects() -> None:
    profiles = [_profile() for _ in range(12)]

    first = [p.worker_id for p in _panel(profiles, project=UUID(int=1))]
    again = [p.worker_id for p in _panel(list(reversed(profiles)), project=UUID(int=1))]
    other = [p.worker_id for p in _panel(profiles, project=UUID(int=2))]

    assert first == again
    assert first != other

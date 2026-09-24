from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.engagements.schemas import StandingRecord
from app.modules.governance.schemas import TieringRules
from app.modules.standing.rules import evaluate, months_before
from tests.support import _seed_policy_rows

TODAY = date(2026, 9, 25)
RULES = TieringRules.model_validate(
    next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering")
)
ALL_TRUE = {"a": True, "b": True, "c": True}


def _record(
    reviewer: UUID | None = None,
    answers: dict[str, bool] | None = None,
    *,
    days_ago: int = 30,
    excluded: bool = False,
) -> StandingRecord:
    return StandingRecord(
        engagement_id=uuid4(),
        completed_on=TODAY - timedelta(days=days_ago),
        reviewer_id=reviewer,
        answers=answers,
        excluded=excluded,
    )


def test_no_history_is_unrated() -> None:
    result = evaluate([], RULES, TODAY)

    assert (result.tier, result.completed, result.distinct_reviewers, result.positive_ratio) == (
        "unrated",
        0,
        0,
        0.0,
    )


def test_a_completed_engagement_without_feedback_is_not_enough_for_tier_1() -> None:
    assert evaluate([_record()], RULES, TODAY).tier == "unrated"


def test_one_positive_review_reaches_tier_1() -> None:
    assert evaluate([_record(uuid4(), ALL_TRUE)], RULES, TODAY).tier == "tier_1"


def test_three_engagements_two_reviewers_and_80_percent_reach_tier_2() -> None:
    ama, kwame = uuid4(), uuid4()
    mostly = {"a": True, "b": False, "c": False}  # 7 of 9 true overall = 0.78
    records = [_record(ama, ALL_TRUE), _record(kwame, ALL_TRUE), _record(ama, mostly)]

    result = evaluate(records, RULES, TODAY)

    assert (result.tier, result.distinct_reviewers) == ("tier_1", 2)
    assert result.positive_ratio == pytest.approx(0.7778, abs=1e-4)
    assert evaluate([*records[:2], _record(ama, ALL_TRUE)], RULES, TODAY).tier == "tier_2"


def test_one_reviewer_cannot_reach_tier_2_alone() -> None:
    ama = uuid4()
    records = [_record(ama, ALL_TRUE) for _ in range(5)]

    assert evaluate(records, RULES, TODAY).tier == "tier_1"


def test_excluded_and_out_of_window_records_do_not_count() -> None:
    old = _record(uuid4(), ALL_TRUE, days_ago=24 * 31 + 5)
    excluded = _record(uuid4(), ALL_TRUE, excluded=True)

    result = evaluate([old, excluded], RULES, TODAY)

    assert (result.tier, result.completed) == ("unrated", 0)


def test_the_window_start_is_inclusive() -> None:
    boundary = StandingRecord(
        engagement_id=uuid4(),
        completed_on=months_before(TODAY, 24),
        reviewer_id=uuid4(),
        answers=ALL_TRUE,
        excluded=False,
    )

    assert evaluate([boundary], RULES, TODAY).tier == "tier_1"


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2026, 3, 31), 1, date(2026, 2, 28)),
        (date(2028, 3, 31), 1, date(2028, 2, 29)),
        (date(2026, 1, 15), 24, date(2024, 1, 15)),
        (date(2026, 1, 15), 13, date(2024, 12, 15)),
    ],
)
def test_months_before(day: date, months: int, expected: date) -> None:
    assert months_before(day, months) == expected


def test_factors_report_the_inputs() -> None:
    result = evaluate([_record(uuid4(), ALL_TRUE)], RULES, TODAY)

    assert result.factors() == {
        "completed": 1,
        "distinct_reviewers": 1,
        "positive_ratio": 1.0,
        "window_start": "2024-09-25",
    }

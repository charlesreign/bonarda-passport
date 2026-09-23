"""The tier rules engine (spec §7.3): a pure function. No database, no clock."""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.engagements.schemas import StandingRecord
from app.modules.governance.schemas import TieringRules


def months_before(day: date, months: int) -> date:
    """The same calendar day `months` earlier, clamped to the month's last day."""
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True, slots=True)
class Evaluation:
    tier: str
    completed: int
    distinct_reviewers: int
    positive_ratio: float
    window_start: date

    def factors(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "distinct_reviewers": self.distinct_reviewers,
            "positive_ratio": round(self.positive_ratio, 4),
            "window_start": self.window_start.isoformat(),
        }


def evaluate(records: Iterable[StandingRecord], rules: TieringRules, today: date) -> Evaluation:
    window_start = months_before(today, rules.window_months)
    counted = [r for r in records if not r.excluded and r.completed_on >= window_start]
    reviewed = [r for r in counted if r.answers is not None]
    reviewers = {r.reviewer_id for r in reviewed if r.reviewer_id is not None}
    answers = [value for r in reviewed if r.answers is not None for value in r.answers.values()]
    ratio = sum(answers) / len(answers) if answers else 0.0
    tier = next(
        (
            rule.tier
            for rule in rules.tiers
            if len(counted) >= rule.min_completed
            and len(reviewers) >= rule.min_distinct_reviewers
            and ratio >= rule.min_positive_ratio
        ),
        rules.default,
    )
    return Evaluation(
        tier=tier,
        completed=len(counted),
        distinct_reviewers=len(reviewers),
        positive_ratio=ratio,
        window_start=window_start,
    )

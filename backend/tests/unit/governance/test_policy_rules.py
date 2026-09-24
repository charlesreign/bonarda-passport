import copy
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.governance.schemas import MatchingRules, TieringRules
from tests.support import _seed_policy_rows


def _seed(kind: str) -> dict[str, Any]:
    return copy.deepcopy(next(p["rules"] for p in _seed_policy_rows() if p["kind"] == kind))


def test_seed_policies_are_valid() -> None:
    TieringRules.model_validate(_seed("tiering"))
    MatchingRules.model_validate(_seed("matching"))


def test_tiers_must_be_listed_highest_first() -> None:
    rules = _seed("tiering")
    rules["tiers"].reverse()

    with pytest.raises(ValidationError, match="highest first"):
        TieringRules.model_validate(rules)


def test_tiers_must_be_unique() -> None:
    rules = _seed("tiering")
    rules["tiers"][1]["tier"] = "tier_2"

    with pytest.raises(ValidationError):
        TieringRules.model_validate(rules)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["weights"].update(tier=0.2, verified_skills=0.45),  # tier above 15% (FR-3.4)
        lambda r: r["weights"].update(availability=0.2),  # sums to 1.05
        lambda r: r["tier_weights"].pop("tier_1"),
        lambda r: r["weights"].update(selection_frequency=0.0),  # FR-6.2: no such factor
        lambda r: r["first_shot"].update(panel_size=0),
    ],
)
def test_invalid_matching_rules_are_rejected(mutate: Any) -> None:
    rules = _seed("matching")
    mutate(rules)

    with pytest.raises(ValidationError):
        MatchingRules.model_validate(rules)

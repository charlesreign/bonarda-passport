import enum


class FirstShotOutcome(enum.StrEnum):
    SHOWN = "shown"
    SHORTLISTED = "shortlisted"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    PASSED = "passed"


class PassReason(enum.StrEnum):
    """Fixed reason codes for passing on a first-shot candidate (FR-4.7)."""

    SKILLS_MISMATCH = "skills_mismatch"
    AVAILABILITY_MISMATCH = "availability_mismatch"
    RATE_MISMATCH = "rate_mismatch"
    LOCATION_MISMATCH = "location_mismatch"
    ALREADY_STAFFED = "already_staffed"
    OTHER = "other"


DETAIL_OUTCOMES = frozenset(
    {FirstShotOutcome.SHORTLISTED, FirstShotOutcome.CONTACTED, FirstShotOutcome.ENGAGED}
)
DECIDED_OUTCOMES = frozenset({FirstShotOutcome.PASSED, FirstShotOutcome.ENGAGED})

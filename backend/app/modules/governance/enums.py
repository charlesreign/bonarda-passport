import enum


class PolicyKind(enum.StrEnum):
    TIERING = "tiering"
    MATCHING = "matching"
    CONCENTRATION = "concentration"  # rules schema arrives in Plan 4
    RETENTION = "retention"  # rules schema arrives in Plan 4


class PolicyStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class DisputeTargetType(enum.StrEnum):
    FEEDBACK = "feedback"
    STANDING_CHANGE = "standing_change"
    ENGAGEMENT = "engagement"


class DisputeStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class DisputeResolution(enum.StrEnum):
    UPHELD = "upheld"
    REJECTED = "rejected"

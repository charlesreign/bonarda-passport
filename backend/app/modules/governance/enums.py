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

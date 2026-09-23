import enum


class WorkerType(enum.StrEnum):
    FREELANCER = "freelancer"
    CONTRACTOR = "contractor"  # employees later, without a breaking change (NFR-6.2)


class WorkerStatus(enum.StrEnum):
    ACTIVE = "active"  # has an active engagement
    DORMANT = "dormant"  # no active engagement; still searchable (FR-9.7)
    OFFBOARDED = "offboarded"
    ANONYMIZED = "anonymized"  # erasure / retention expiry


class OnboardingState(enum.StrEnum):
    INVITED = "invited"
    PROFILE_COMPLETE = "profile_complete"


class StandingTier(enum.StrEnum):
    UNRATED = "unrated"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"  # "Trusted"


class AvailabilityStatus(enum.StrEnum):
    AVAILABLE = "available"
    AVAILABLE_FROM = "available_from"
    UNAVAILABLE = "unavailable"


class VerificationStatus(enum.StrEnum):
    UNVERIFIED = "unverified"
    SELF_REPORTED = "self_reported"
    BONARDA_VERIFIED = "bonarda_verified"  # distinct reviewers ≥ policy threshold (FR-2.2)


class ClaimSource(enum.StrEnum):
    SELF = "self"
    EXTERNAL = "external"
    REVIEW = "review"


class ConsentPurpose(enum.StrEnum):
    CROSS_REGION_MATCHING = "cross_region_matching"  # NFR-4.3
    EXTERNAL_PREFILL = "external_prefill"

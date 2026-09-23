import enum


class ProjectStatus(enum.StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class EngagementPath(enum.StrEnum):
    FIRST_TIME = "first_time"  # FR-5.1
    REACTIVATION = "reactivation"  # FR-4.3


class EngagementStatus(enum.StrEnum):
    PENDING_SIGNATURE = "pending_signature"  # recorded; contract not yet sent
    AWAITING_SIGNATURE = "awaiting_signature"  # envelope sent
    SIGNED = "signed"  # signed; start date still ahead
    ACTIVE = "active"  # billable
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkMode(enum.StrEnum):
    REMOTE = "remote"
    ONSITE = "onsite"
    HYBRID = "hybrid"


OPEN_STATUSES = frozenset(
    {
        EngagementStatus.PENDING_SIGNATURE,
        EngagementStatus.AWAITING_SIGNATURE,
        EngagementStatus.SIGNED,
        EngagementStatus.ACTIVE,
    }
)

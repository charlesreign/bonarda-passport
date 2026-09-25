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

# Work that has actually happened: a signed contract or later (FR-5.3). The
# same rule decides reactivation history and roster engagement counts.
HISTORY_STATUSES = (
    EngagementStatus.SIGNED,
    EngagementStatus.ACTIVE,
    EngagementStatus.COMPLETED,
)


class CancelCause(enum.StrEnum):
    """Why an engagement ended `cancelled` (offer-decline spec §3)."""

    WORKER_DECLINED = "worker_declined"  # in the app
    ESIGN_DECLINED = "esign_declined"  # at the e-sign provider
    WORKER_ACCOUNT_MISSING = "worker_account_missing"  # erased before the contract went out


class DeclineReason(enum.StrEnum):
    RATE = "rate"
    DATES = "dates"
    SCOPE = "scope"
    AVAILABILITY = "availability"
    OTHER = "other"


# Declines are recorded, never scored: no standing or roster query reads these.
DECLINE_CAUSES = frozenset({CancelCause.WORKER_DECLINED, CancelCause.ESIGN_DECLINED})

# An offer can be declined until its contract is signed.
DECLINABLE_STATUSES = frozenset(
    {EngagementStatus.PENDING_SIGNATURE, EngagementStatus.AWAITING_SIGNATURE}
)

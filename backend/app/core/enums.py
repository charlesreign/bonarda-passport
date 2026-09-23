import enum


class UserRole(enum.StrEnum):
    PM = "pm"
    PEOPLE_OPS = "people_ops"
    FINANCE = "finance"
    WORKER = "worker"
    ADMIN = "admin"


class AuthProvider(enum.StrEnum):
    CORPORATE_SSO = "corporate_sso"  # FR-9.1
    MAGIC_LINK = "magic_link"  # FR-9.2


class AccountStatus(enum.StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"  # SCIM deactivation (FR-9.12)

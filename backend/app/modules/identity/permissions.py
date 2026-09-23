"""Fixed role → permission matrix (FR-9.3). Roles are never inferred from job
titles. docs/permissions.md is generated from this file and checked in CI.

PM leadership governance access is the `can_view_governance` account flag,
checked by the governance module in addition to GOVERNANCE_READ (Plan 4)."""

import sys
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from app.core.enums import UserRole


class Permission(StrEnum):
    WORKER_READ_SELF = "worker:read_self"
    WORKER_UPDATE_SELF = "worker:update_self"
    WORKER_READ = "worker:read"  # always further limited by VisibilityPolicy
    WORKER_INVITE = "worker:invite"
    DISPUTE_FILE = "dispute:file"
    DISPUTE_RESOLVE = "dispute:resolve"
    PROJECT_MANAGE = "project:manage"
    PROJECT_STAFF_ASSIGN = "project:staff_assign"
    ROSTER_SEARCH = "roster:search"
    ENGAGEMENT_CREATE = "engagement:create"
    ENGAGEMENT_REACTIVATE = "engagement:reactivate"
    ENGAGEMENT_READ_BILLING = "engagement:read_billing"
    FEEDBACK_SUBMIT = "feedback:submit"
    FIRST_SHOT_REVIEW = "first_shot:review"
    ACCESS_GRANT_MANAGE = "access_grant:manage"
    POLICY_PROPOSE = "policy:propose"
    POLICY_ACTIVATE = "policy:activate"
    STANDING_OVERRIDE = "standing:override"
    GOVERNANCE_READ = "governance:read"
    AUDIT_READ = "audit:read"
    SKILL_MANAGE = "skill:manage"


P = Permission
ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = MappingProxyType(
    {
        UserRole.WORKER: frozenset({P.WORKER_READ_SELF, P.WORKER_UPDATE_SELF, P.DISPUTE_FILE}),
        UserRole.PM: frozenset(
            {
                P.WORKER_READ,
                P.WORKER_INVITE,
                P.PROJECT_MANAGE,
                P.ROSTER_SEARCH,
                P.ENGAGEMENT_CREATE,
                P.ENGAGEMENT_REACTIVATE,
                P.FEEDBACK_SUBMIT,
                P.FIRST_SHOT_REVIEW,
            }
        ),
        UserRole.PEOPLE_OPS: frozenset(
            {
                P.WORKER_READ,
                P.PROJECT_MANAGE,
                P.PROJECT_STAFF_ASSIGN,
                P.DISPUTE_RESOLVE,
                P.ACCESS_GRANT_MANAGE,
                P.POLICY_PROPOSE,
                P.POLICY_ACTIVATE,
                P.STANDING_OVERRIDE,
                P.GOVERNANCE_READ,
                P.AUDIT_READ,
                P.SKILL_MANAGE,
            }
        ),
        UserRole.FINANCE: frozenset({P.ENGAGEMENT_READ_BILLING}),
        UserRole.ADMIN: frozenset({P.WORKER_READ, P.GOVERNANCE_READ, P.AUDIT_READ}),
    }
)
_ROLE_ORDER = (UserRole.PM, UserRole.PEOPLE_OPS, UserRole.FINANCE, UserRole.WORKER, UserRole.ADMIN)


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def render_markdown() -> str:
    header = "| Permission | " + " | ".join(r.value for r in _ROLE_ORDER) + " |"
    divider = "|---|" + "---|" * len(_ROLE_ORDER)
    rows = [
        f"| `{p.value}` | "
        + " | ".join("✓" if has_permission(r, p) else "" for r in _ROLE_ORDER)
        + " |"
        for p in Permission
    ]
    return "\n".join(
        [
            "# Role permission matrix",
            "",
            "Generated from `backend/app/modules/identity/permissions.py`.",
            "Do not edit by hand; from `backend/` run:",
            "",
            "    python -m app.modules.identity.permissions ../docs/permissions.md",
            "",
            "`worker:read` is further limited per worker by the visibility policy",
            "(spec §7.1).",
            "",
            header,
            divider,
            *rows,
            "",
        ]
    )


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(render_markdown(), encoding="utf-8", newline="\n")

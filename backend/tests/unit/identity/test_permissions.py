from pathlib import Path

import pytest

from app.core.enums import UserRole
from app.modules.identity.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    has_permission,
    render_markdown,
)

DOCS_FILE = Path(__file__).resolve().parents[4] / "docs" / "permissions.md"


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (UserRole.PM, Permission.ENGAGEMENT_REACTIVATE, True),
        (UserRole.PM, Permission.ACCESS_GRANT_MANAGE, False),
        (UserRole.PM, Permission.AUDIT_READ, False),
        (UserRole.PEOPLE_OPS, Permission.ACCESS_GRANT_MANAGE, True),
        (UserRole.PEOPLE_OPS, Permission.ENGAGEMENT_REACTIVATE, False),
        (UserRole.WORKER, Permission.DISPUTE_FILE, True),
        (UserRole.WORKER, Permission.WORKER_READ, False),
        (UserRole.FINANCE, Permission.ENGAGEMENT_READ_BILLING, True),
        (UserRole.FINANCE, Permission.WORKER_READ, False),
        (UserRole.ADMIN, Permission.AUDIT_READ, True),
        (UserRole.ADMIN, Permission.DISPUTE_RESOLVE, False),
    ],
)
def test_role_matrix(role: UserRole, permission: Permission, allowed: bool) -> None:
    assert has_permission(role, permission) is allowed


def test_every_role_is_defined_and_every_permission_is_granted_somewhere() -> None:
    assert set(ROLE_PERMISSIONS) == set(UserRole)
    granted = set().union(*ROLE_PERMISSIONS.values())
    assert granted == set(Permission)


def test_generated_documentation_is_up_to_date() -> None:
    assert DOCS_FILE.read_text(encoding="utf-8") == render_markdown(), (
        "docs/permissions.md is stale — run from backend/: "
        "python -m app.modules.identity.permissions ../docs/permissions.md"
    )

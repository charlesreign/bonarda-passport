"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.accounts import (
    account_contact,
    active_pm_ids,
    can_view_governance,
    find_worker_account,
    provision_worker_account,
    request_sign_in_link,
    staff_contacts,
    worker_contact,
)
from app.modules.identity.dependencies import CurrentActor, require_permission
from app.modules.identity.permissions import Permission, has_permission
from app.modules.identity.visibility import (
    Visibility,
    VisibilityPolicy,
    VisibilitySource,
    require_visibility,
)

__all__ = [
    "CurrentActor",
    "Permission",
    "Visibility",
    "VisibilityPolicy",
    "VisibilitySource",
    "account_contact",
    "active_pm_ids",
    "can_view_governance",
    "find_worker_account",
    "has_permission",
    "provision_worker_account",
    "request_sign_in_link",
    "require_permission",
    "require_visibility",
    "staff_contacts",
    "worker_contact",
]

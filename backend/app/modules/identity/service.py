"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.accounts import (
    account_contact,
    provision_worker_account,
    request_sign_in_link,
)
from app.modules.identity.dependencies import CurrentActor, require_permission
from app.modules.identity.permissions import Permission
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
    "provision_worker_account",
    "request_sign_in_link",
    "require_permission",
    "require_visibility",
]

"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

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
    "require_permission",
    "require_visibility",
]

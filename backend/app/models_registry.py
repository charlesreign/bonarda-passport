"""Imports every ORM model so Base.metadata is complete for Alembic and tests."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models
from app.modules.identity import models as identity_models

__all__ = ["audit_models", "identity_models", "outbox_models"]

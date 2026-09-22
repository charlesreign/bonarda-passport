"""Imports every ORM model so Base.metadata is complete for Alembic and tests."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models

__all__ = ["audit_models", "outbox_models"]

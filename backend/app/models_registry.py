"""Imports every ORM model so Base.metadata is complete for Alembic, tests,
and the API/worker processes (cross-module FKs resolve by table name)."""

from app.core.audit import models as audit_models
from app.core.outbox import models as outbox_models
from app.modules.engagements import models as engagements_models
from app.modules.governance import models as governance_models
from app.modules.identity import models as identity_models
from app.modules.passport import models as passport_models
from app.modules.standing import models as standing_models

__all__ = [
    "audit_models",
    "engagements_models",
    "governance_models",
    "identity_models",
    "outbox_models",
    "passport_models",
    "standing_models",
]

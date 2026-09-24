import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.modules.governance.enums import PolicyKind, PolicyStatus


class PolicyConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned rule set People Ops controls (NFR-5.1, NFR-9.2). Once
    proposed, a row changes only through its status lifecycle (draft → active
    → retired); the `policy_configs_guard` trigger (migration 0012) enforces it."""

    __tablename__ = "policy_configs"

    kind: Mapped[PolicyKind] = mapped_column(pg_enum(PolicyKind), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PolicyStatus] = mapped_column(
        pg_enum(PolicyStatus),
        default=PolicyStatus.DRAFT,
        server_default=PolicyStatus.DRAFT.value,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    activated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_policy_configs_kind_version"),
        Index(
            "uq_policy_configs_active_kind",
            "kind",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("activated_by_id <> created_by_id", name="two_person"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("status = 'draft' OR activated_at IS NOT NULL", name="activated_when_live"),
    )

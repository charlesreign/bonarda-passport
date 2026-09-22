import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.types import pg_enum
from app.core.enums import AccountStatus, AuthProvider, UserRole


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_accounts"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # lowercase
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole), nullable=False)
    auth_provider: Mapped[AuthProvider] = mapped_column(pg_enum(AuthProvider), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        pg_enum(AccountStatus),
        default=AccountStatus.ACTIVE,
        server_default=AccountStatus.ACTIVE.value,
        nullable=False,
    )
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    # FK to workers.id is added by Plan 2's migration, once the table exists.
    worker_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    can_view_governance: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per issued refresh token. Rotation revokes the row and inserts a
    new one in the same family; reuse of a revoked row revokes the family."""

    __tablename__ = "refresh_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    family_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amr: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default=text("'{}'"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_refresh_sessions_family_id", "family_id"),
        Index("ix_refresh_sessions_user_id", "user_id"),
    )


class AccessGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """FR-9.5 — scoped, expiring detail visibility for a PM. Reads check
    expires_at, so a grant stops working the moment it expires (NFR-3.8)."""

    __tablename__ = "access_grants"

    granted_to_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # FK to workers.id is added by Plan 2's migration.
    scoped_worker_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_access_grants_lookup",
            "granted_to_id",
            "scoped_worker_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_access_grants_expiry", "expires_at", postgresql_where=text("revoked_at IS NULL")),
    )

"""identity: user accounts, refresh sessions, access grants

Revision ID: 0002_identity
Revises: 0001_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_identity"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("pm", "people_ops", "finance", "worker", "admin", name="userrole"),
            nullable=False,
        ),
        sa.Column(
            "auth_provider",
            sa.Enum("corporate_sso", "magic_link", name="authprovider"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "revoked", name="accountstatus"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("oidc_subject", sa.String(255), nullable=True),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "can_view_governance", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_user_accounts"),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
        sa.UniqueConstraint("oidc_subject", name="uq_user_accounts_oidc_subject"),
        sa.UniqueConstraint("worker_id", name="uq_user_accounts_worker_id"),
    )

    op.create_table(
        "refresh_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "amr", postgresql.ARRAY(sa.String(20)), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name="fk_refresh_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
    )
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])

    op.create_table(
        "access_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("granted_to_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scoped_worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_access_grants"),
        sa.ForeignKeyConstraint(
            ["granted_to_id"],
            ["user_accounts.id"],
            name="fk_access_grants_granted_to_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"],
            ["user_accounts.id"],
            name="fk_access_grants_granted_by_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_access_grants_lookup",
        "access_grants",
        ["granted_to_id", "scoped_worker_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_access_grants_expiry",
        "access_grants",
        ["expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("access_grants")
    op.drop_table("refresh_sessions")
    op.drop_table("user_accounts")
    op.execute("DROP TYPE accountstatus")
    op.execute("DROP TYPE authprovider")
    op.execute("DROP TYPE userrole")

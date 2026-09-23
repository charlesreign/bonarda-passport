"""refresh_sessions: revoked_reason distinguishes rotation from admin/logout/reuse revocation

Revision ID: 0003_refresh_revoked_reason
Revises: 0002_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_refresh_revoked_reason"
down_revision: str | None = "0002_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_sessions", sa.Column("revoked_reason", sa.String(20), nullable=True))
    op.create_check_constraint(
        op.f("ck_refresh_sessions_revoked_reason_valid"),
        "refresh_sessions",
        "revoked_reason IS NULL OR revoked_reason IN ('rotated','logout','admin','reuse')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_refresh_sessions_revoked_reason_valid"), "refresh_sessions", type_="check"
    )
    op.drop_column("refresh_sessions", "revoked_reason")

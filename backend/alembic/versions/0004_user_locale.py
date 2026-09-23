"""user_accounts.locale: language for mail and UI defaults

Revision ID: 0004_user_locale
Revises: 0003_refresh_revoked_reason
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_user_locale"
down_revision: str | None = "0003_refresh_revoked_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("locale", sa.String(5), server_default="en", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_locale_supported"), "user_accounts", "locale IN ('en','fr')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_user_accounts_locale_supported"), "user_accounts", type_="check")
    op.drop_column("user_accounts", "locale")

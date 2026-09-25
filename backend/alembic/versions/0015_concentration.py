"""governance: concentration_rollups

Revision ID: 0015_concentration
Revises: 0014_policy_seeds
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_concentration"
down_revision: str | None = "0014_policy_seeds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "concentration_rollups",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column("engagements_total", sa.Integer(), nullable=False),
        sa.Column("engagements_repeat", sa.Integer(), nullable=False),
        sa.Column("share", sa.Float(), nullable=False),
        sa.Column("first_shot_shown", sa.Integer(), nullable=False),
        sa.Column("first_shot_engaged", sa.Integer(), nullable=False),
        sa.Column("tier_counts", postgresql.JSONB(), nullable=False),
        sa.Column("alerted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("policy_version_id", _UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_concentration_rollups"),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_configs.id"],
            name="fk_concentration_rollups_policy_version_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("period_end", "scope", name="uq_concentration_rollups_period_scope"),
    )


def downgrade() -> None:
    op.drop_table("concentration_rollups")

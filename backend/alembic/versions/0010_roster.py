"""roster: roster_profiles read-model

Revision ID: 0010_roster
Revises: 0009_standing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_roster"
down_revision: str | None = "0009_standing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "roster_profiles",
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("onboarding_state", sa.String(20), nullable=False),
        sa.Column("data_region", sa.String(8), nullable=False),
        sa.Column("cross_region_ok", sa.Boolean(), nullable=False),
        sa.Column("standing_tier", sa.String(20), nullable=False),
        sa.Column(
            "skill_ids", postgresql.ARRAY(_UUID), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "verified_skill_ids",
            postgresql.ARRAY(_UUID),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("base_location", sa.String(120), nullable=True),
        sa.Column("availability_status", sa.String(20), nullable=False),
        sa.Column("available_from", sa.Date(), nullable=True),
        sa.Column("engagements_total", sa.Integer(), nullable=False),
        sa.Column("engagements_last_12m", sa.Integer(), nullable=False),
        sa.Column("last_engaged_on", sa.Date(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name="pk_roster_profiles"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_roster_profiles_worker_id", ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_roster_profiles_skill_ids", "roster_profiles", ["skill_ids"], postgresql_using="gin"
    )
    op.create_index(
        "ix_roster_profiles_verified_skill_ids",
        "roster_profiles",
        ["verified_skill_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_roster_profiles_region_availability",
        "roster_profiles",
        ["data_region", "availability_status"],
        postgresql_where=sa.text("status IN ('active','dormant')"),
    )
    op.create_index(
        "ix_roster_profiles_engagements_last_12m", "roster_profiles", ["engagements_last_12m"]
    )
    op.create_index(
        "ix_roster_profiles_display_name_trgm",
        "roster_profiles",
        ["display_name"],
        postgresql_using="gin",
        postgresql_ops={"display_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_table("roster_profiles")
    # pg_trgm stays installed: other objects may use it, and dropping an
    # extension is not a schema change this revision owns.

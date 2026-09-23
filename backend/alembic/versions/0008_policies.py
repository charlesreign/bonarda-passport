"""governance: policy_configs with seeded tiering and matching v1

Revision ID: 0008_policies
Revises: 0007_engagements
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_policies"
down_revision: str | None = "0007_engagements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)

# Seed policies (spec §7.3, §7.4). Authored by the system (created_by_id NULL),
# active from the first deploy. tests/support.py re-inserts these after each
# test's TRUNCATE, so this list is the single source of truth.
SEED_POLICIES: list[dict[str, Any]] = [
    {
        "kind": "tiering",
        "version": 1,
        "notes": "Seed tiering policy (spec §7.3)",
        "rules": {
            "window_months": 24,
            "tiers": [
                {
                    "tier": "tier_2",
                    "min_completed": 3,
                    "min_distinct_reviewers": 2,
                    "min_positive_ratio": 0.8,
                },
                {
                    "tier": "tier_1",
                    "min_completed": 1,
                    "min_distinct_reviewers": 1,
                    "min_positive_ratio": 0.6,
                },
            ],
            "default": "unrated",
            "skill_verification": {"min_distinct_reviewers": 2},
        },
    },
    {
        "kind": "matching",
        "version": 1,
        "notes": "Seed matching policy (spec §7.4)",
        "rules": {
            "weights": {
                "verified_skills": 0.5,
                "self_reported_skills": 0.2,
                "availability": 0.15,
                "tier": 0.15,
            },
            "tier_weights": {"unrated": 0.0, "tier_1": 0.5, "tier_2": 1.0},
            "availability_near_days": 14,
            "first_shot": {
                "panel_size": 5,
                "underused_max_engagements_12m": 1,
                "exclude_top_candidates": 10,
            },
        },
    },
]


def upgrade() -> None:
    policy_configs = op.create_table(
        "policy_configs",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("tiering", "matching", "concentration", "retention", name="policykind"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "retired", name="policystatus"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by_id", _UUID, nullable=True),
        sa.Column("activated_by_id", _UUID, nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policy_configs"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user_accounts.id"],
            name="fk_policy_configs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_id"],
            ["user_accounts.id"],
            name="fk_policy_configs_activated_by_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("kind", "version", name="uq_policy_configs_kind_version"),
        sa.CheckConstraint(
            "activated_by_id <> created_by_id", name=op.f("ck_policy_configs_two_person")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_policy_configs_version_positive")),
    )
    op.create_index(
        "uq_policy_configs_active_kind",
        "policy_configs",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        policy_configs,
        [{**seed, "status": "active", "activated_at": now} for seed in SEED_POLICIES],
    )


def downgrade() -> None:
    op.drop_index("uq_policy_configs_active_kind", table_name="policy_configs")
    op.drop_table("policy_configs")
    op.execute("DROP TYPE policystatus")
    op.execute("DROP TYPE policykind")

"""standing: append-only standing_changes and skill_evidence

Revision ID: 0009_standing
Revises: 0008_policies
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_standing"
down_revision: str | None = "0008_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
# Created by 0005_passport; reused here.
_TIER = postgresql.ENUM("unrated", "tier_1", "tier_2", name="standingtier", create_type=False)


def upgrade() -> None:
    op.create_table(
        "standing_changes",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("previous_tier", _TIER, nullable=False),
        sa.Column("new_tier", _TIER, nullable=False),
        sa.Column("contributing_factors", postgresql.JSONB(), nullable=False),
        sa.Column("policy_version_id", _UUID, nullable=True),
        sa.Column("trigger_event_id", _UUID, nullable=True),
        sa.Column("actor_id", _UUID, nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_standing_changes"),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.id"],
            name="fk_standing_changes_worker_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_configs.id"],
            name="fk_standing_changes_policy_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_accounts.id"],
            name="fk_standing_changes_actor_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_standing_changes_worker_created", "standing_changes", ["worker_id", "created_at"]
    )
    # forbid_mutation() was created by 0001_core for audit_log.
    op.execute(
        "CREATE TRIGGER standing_changes_append_only BEFORE UPDATE OR DELETE "
        "ON standing_changes FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
    )

    op.create_table(
        "skill_evidence",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("skill_id", _UUID, nullable=False),
        sa.Column("engagement_id", _UUID, nullable=False),
        sa.Column("reviewer_id", _UUID, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_evidence"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_skill_evidence_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_skill_evidence_skill_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name="fk_skill_evidence_engagement_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["user_accounts.id"],
            name="fk_skill_evidence_reviewer_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "worker_id", "skill_id", "reviewer_id", name="uq_skill_evidence_worker_skill_reviewer"
        ),
    )


def downgrade() -> None:
    op.drop_table("skill_evidence")
    op.execute("DROP TRIGGER IF EXISTS standing_changes_append_only ON standing_changes")
    op.drop_index("ix_standing_changes_worker_created", table_name="standing_changes")
    op.drop_table("standing_changes")

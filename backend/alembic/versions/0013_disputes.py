"""governance: disputes

Revision ID: 0013_disputes
Revises: 0012_policy_guards
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_disputes"
down_revision: str | None = "0012_policy_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "disputes",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column(
            "target_type",
            sa.Enum("feedback", "standing_change", "engagement", name="disputetargettype"),
            nullable=False,
        ),
        sa.Column("target_id", _UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "resolved", name="disputestatus"),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "resolution", sa.Enum("upheld", "rejected", name="disputeresolution"), nullable=True
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolver_id", _UUID, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_disputes"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_disputes_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resolver_id"],
            ["user_accounts.id"],
            name="fk_disputes_resolver_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name=op.f("ck_disputes_resolved_consistent"),
        ),
    )
    op.create_index("ix_disputes_status_due", "disputes", ["status", "due_at"])
    op.create_index("ix_disputes_worker", "disputes", ["worker_id"])
    op.create_index(
        "uq_disputes_open_target",
        "disputes",
        ["target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_disputes_open_target", table_name="disputes")
    op.drop_index("ix_disputes_worker", table_name="disputes")
    op.drop_index("ix_disputes_status_due", table_name="disputes")
    op.drop_table("disputes")
    op.execute("DROP TYPE disputeresolution")
    op.execute("DROP TYPE disputestatus")
    op.execute("DROP TYPE disputetargettype")

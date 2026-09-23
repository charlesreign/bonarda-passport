"""engagements: engagements and feedback

Revision ID: 0007_engagements
Revises: 0006_projects
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_engagements"
down_revision: str | None = "0006_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column[object]:
    return sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    op.create_table(
        "engagements",
        _id(),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column(
            "path", sa.Enum("first_time", "reactivation", name="engagementpath"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending_signature",
                "awaiting_signature",
                "signed",
                "active",
                "completed",
                "cancelled",
                name="engagementstatus",
            ),
            server_default="pending_signature",
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "work_mode", sa.Enum("remote", "onsite", "hybrid", name="workmode"), nullable=False
        ),
        sa.Column("location", sa.String(120), nullable=True),
        sa.Column("contract_terms", postgresql.JSONB(), nullable=False),
        sa.Column("prefilled_from_engagement_id", _UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        _ts("contract_sent_at"),
        _ts("signed_at"),
        _ts("billable_start_at"),
        _ts("completed_at"),
        _ts("payroll_signaled_at"),
        _ts("stuck_flagged_at"),
        sa.Column("esign_envelope_id", sa.String(120), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("created_by_id", _UUID, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_engagements"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_engagements_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_engagements_project_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["prefilled_from_engagement_id"],
            ["engagements.id"],
            name="fk_engagements_prefilled_from_engagement_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user_accounts.id"],
            name="fk_engagements_created_by_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("esign_envelope_id", name="uq_engagements_esign_envelope_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_engagements_idempotency_key"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name=op.f("ck_engagements_dates_ordered")
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_engagements_rate_positive")),
    )
    op.create_index("ix_engagements_worker_start", "engagements", ["worker_id", "start_date"])
    op.create_index("ix_engagements_project", "engagements", ["project_id"])
    op.create_index(
        "ix_engagements_in_flight",
        "engagements",
        ["status"],
        postgresql_where=sa.text("status IN ('pending_signature','awaiting_signature')"),
    )
    op.create_index(
        "uq_engagements_open_worker_project",
        "engagements",
        ["worker_id", "project_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_signature','awaiting_signature','signed','active')"
        ),
    )

    op.create_table(
        "feedback",
        _id(),
        sa.Column("engagement_id", _UUID, nullable=False),
        sa.Column("reviewer_id", _UUID, nullable=True),
        sa.Column("structured_answers", postgresql.JSONB(), nullable=False),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column(
            "skill_ids_demonstrated",
            postgresql.ARRAY(_UUID),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "excluded_from_standing", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name="fk_feedback_engagement_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["user_accounts.id"],
            name="fk_feedback_reviewer_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("engagement_id", name="uq_feedback_engagement_id"),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_index("uq_engagements_open_worker_project", table_name="engagements")
    op.drop_index("ix_engagements_in_flight", table_name="engagements")
    op.drop_index("ix_engagements_project", table_name="engagements")
    op.drop_index("ix_engagements_worker_start", table_name="engagements")
    op.drop_table("engagements")
    for enum_name in ("workmode", "engagementstatus", "engagementpath"):
        op.execute(f"DROP TYPE {enum_name}")

"""roster: first_shot_reviews

Revision ID: 0011_first_shot
Revises: 0010_roster
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_first_shot"
down_revision: str | None = "0010_roster"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "first_shot_reviews",
        sa.Column("id", _UUID, server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("worker_id", _UUID, nullable=False),
        sa.Column("pm_id", _UUID, nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "shown", "shortlisted", "contacted", "engaged", "passed", name="firstshotoutcome"
            ),
            nullable=False,
        ),
        sa.Column(
            "reason_code",
            sa.Enum(
                "skills_mismatch",
                "availability_mismatch",
                "rate_mismatch",
                "location_mismatch",
                "already_staffed",
                "other",
                name="passreason",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_first_shot_reviews"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_first_shot_reviews_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.id"],
            name="fk_first_shot_reviews_worker_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pm_id"],
            ["user_accounts.id"],
            name="fk_first_shot_reviews_pm_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("project_id", "worker_id", name="uq_first_shot_reviews_project_worker"),
        sa.CheckConstraint(
            "(outcome = 'passed') = (reason_code IS NOT NULL)",
            name=op.f("ck_first_shot_reviews_reason_matches_outcome"),
        ),
    )


def downgrade() -> None:
    op.drop_table("first_shot_reviews")
    op.execute("DROP TYPE passreason")
    op.execute("DROP TYPE firstshotoutcome")

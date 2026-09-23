"""engagements: projects and project_staff

Revision ID: 0006_projects
Revises: 0005_passport
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_projects"
down_revision: str | None = "0005_passport"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.func.gen_random_uuid(),
        nullable=False,
    )


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
        "projects",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("client_name", sa.String(200), nullable=True),
        sa.Column("data_region", sa.String(8), nullable=False),
        sa.Column(
            "required_skill_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "closed", name="projectstatus"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user_accounts.id"],
            name="fk_projects_created_by_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name=op.f("ck_projects_dates_ordered"),
        ),
    )

    op.create_table(
        "project_staff",
        _id(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_project_staff"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_staff_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"],
            ["user_accounts.id"],
            name="fk_project_staff_user_account_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_project_staff_active_user",
        "project_staff",
        ["user_account_id"],
        postgresql_where=sa.text("active_to IS NULL"),
    )
    op.create_index(
        "uq_project_staff_active",
        "project_staff",
        ["project_id", "user_account_id"],
        unique=True,
        postgresql_where=sa.text("active_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_staff_active", table_name="project_staff")
    op.drop_index("ix_project_staff_active_user", table_name="project_staff")
    op.drop_table("project_staff")
    op.drop_table("projects")
    op.execute("DROP TYPE projectstatus")

"""passport: workers, skills, skill claims, consents; FKs from identity to workers

Revision ID: 0005_passport
Revises: 0004_user_locale

Adding the FKs fails if user_accounts.worker_id or access_grants.scoped_worker_id
hold ids with no workers row (possible only in a dev database built before this
plan). That failure is deliberate: fix or delete such rows by hand rather than
have a migration silently delete data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_passport"
down_revision: str | None = "0004_user_locale"
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
        "workers",
        _id(),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column(
            "worker_type", sa.Enum("freelancer", "contractor", name="workertype"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("active", "dormant", "offboarded", "anonymized", name="workerstatus"),
            server_default="dormant",
            nullable=False,
        ),
        sa.Column(
            "onboarding_state",
            sa.Enum("invited", "profile_complete", name="onboardingstate"),
            server_default="invited",
            nullable=False,
        ),
        sa.Column(
            "standing_tier",
            sa.Enum("unrated", "tier_1", "tier_2", name="standingtier"),
            server_default="unrated",
            nullable=False,
        ),
        sa.Column("data_region", sa.String(8), nullable=False),
        sa.Column("base_location", sa.String(120), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(10)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "availability_status",
            sa.Enum("available", "available_from", "unavailable", name="availabilitystatus"),
            server_default="available",
            nullable=False,
        ),
        sa.Column("available_from", sa.Date(), nullable=True),
        sa.Column("dormant_since", sa.Date(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_workers"),
    )
    op.create_index("ix_workers_status_region", "workers", ["status", "data_region"])

    op.create_table(
        "skills",
        _id(),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name_i18n", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_skills"),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
    )

    op.create_table(
        "skill_claims",
        _id(),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "verification_status",
            sa.Enum("unverified", "self_reported", "bonarda_verified", name="verificationstatus"),
            server_default="self_reported",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum("self", "external", "review", name="claimsource"),
            server_default="self",
            nullable=False,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_skill_claims"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_skill_claims_worker_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_skill_claims_skill_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("worker_id", "skill_id", name="uq_skill_claims_worker_skill"),
    )
    op.create_index("ix_skill_claims_skill_id", "skill_claims", ["skill_id"])

    op.create_table(
        "consents",
        _id(),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("cross_region_matching", "external_prefill", name="consentpurpose"),
            nullable=False,
        ),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("legal_basis", sa.String(80), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.id"], name="fk_consents_worker_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("worker_id", "purpose", name="uq_consents_worker_purpose"),
    )

    op.create_foreign_key(
        "fk_user_accounts_worker_id",
        "user_accounts",
        "workers",
        ["worker_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_access_grants_scoped_worker_id",
        "access_grants",
        "workers",
        ["scoped_worker_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_access_grants_scoped_worker_id", "access_grants", type_="foreignkey")
    op.drop_constraint("fk_user_accounts_worker_id", "user_accounts", type_="foreignkey")
    op.drop_table("consents")
    op.drop_index("ix_skill_claims_skill_id", table_name="skill_claims")
    op.drop_table("skill_claims")
    op.drop_table("skills")
    op.drop_index("ix_workers_status_region", table_name="workers")
    op.drop_table("workers")
    for enum_name in (
        "consentpurpose",
        "claimsource",
        "verificationstatus",
        "availabilitystatus",
        "standingtier",
        "onboardingstate",
        "workerstatus",
        "workertype",
    ):
        op.execute(f"DROP TYPE {enum_name}")

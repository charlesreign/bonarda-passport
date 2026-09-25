"""governance: seed concentration and retention policies (v1)

Revision ID: 0014_policy_seeds
Revises: 0013_disputes
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0014_policy_seeds"
down_revision: str | None = "0013_disputes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec §2.1 #1 (threshold 65%) and §6.6 (retention periods). Both need sign-off
# (spec §12) before live data. tests/support.py re-inserts these after each test.
SEED_POLICIES: list[dict[str, Any]] = [
    {
        "kind": "concentration",
        "version": 1,
        "notes": "Seed concentration policy (spec §2.1 #1)",
        "rules": {"window_days": 365, "repeat_min_engagements": 3, "alert_share": 0.65},
    },
    {
        "kind": "retention",
        "version": 1,
        "notes": "Seed retention periods (spec §6.6); legal sign-off pending",
        "rules": {
            "dormant_profile_years": 3,
            "feedback_text_years": 6,
            "dispute_text_years": 6,
            "audit_log_years": 7,
        },
    },
]


def upgrade() -> None:
    now = datetime.now(UTC)
    for seed in SEED_POLICIES:
        op.execute(
            sa.text(
                "INSERT INTO policy_configs (kind, version, notes, rules, status, activated_at) "
                "VALUES (CAST(:kind AS policykind), :version, :notes, CAST(:rules AS jsonb), "
                "'active', :activated_at)"
            ).bindparams(
                kind=seed["kind"],
                version=seed["version"],
                notes=seed["notes"],
                rules=json.dumps(seed["rules"]),
                activated_at=now,
            )
        )


def downgrade() -> None:
    op.execute("DELETE FROM policy_configs WHERE kind IN ('concentration', 'retention')")

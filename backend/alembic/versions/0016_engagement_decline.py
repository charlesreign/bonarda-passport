"""engagements: cancel cause and worker decline (offer-decline spec §3)

Revision ID: 0016_engagement_decline
Revises: 0015_concentration
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_engagement_decline"
down_revision: str | None = "0015_concentration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

_CAUSE = postgresql.ENUM(
    "worker_declined",
    "esign_declined",
    "worker_account_missing",
    name="cancelcause",
    create_type=False,
)
_REASON = postgresql.ENUM(
    "rate", "dates", "scope", "availability", "other", name="declinereason", create_type=False
)
_CHECKS = {
    "cancel_cause_when_cancelled": "(status = 'cancelled') = (cancel_cause IS NOT NULL)",
    "declined_at_when_declined": (
        "COALESCE(cancel_cause IN ('worker_declined', 'esign_declined'), false)"
        " = (declined_at IS NOT NULL)"
    ),
    "reason_only_for_worker_decline": "decline_reason IS NULL OR cancel_cause = 'worker_declined'",
    "worker_decline_has_reason": (
        "cancel_cause IS DISTINCT FROM 'worker_declined' OR decline_reason IS NOT NULL"
    ),
    "note_needs_reason": "decline_note IS NULL OR decline_reason IS NOT NULL",
}


def upgrade() -> None:
    bind = op.get_bind()
    _CAUSE.create(bind)
    _REASON.create(bind)
    op.add_column("engagements", sa.Column("cancel_cause", _CAUSE, nullable=True))
    op.add_column("engagements", sa.Column("declined_at", sa.DateTime(timezone=True)))
    op.add_column("engagements", sa.Column("decline_reason", _REASON, nullable=True))
    op.add_column("engagements", sa.Column("decline_note", sa.String(500)))
    op.add_column("engagements", sa.Column("void_requested_at", sa.DateTime(timezone=True)))

    # Until now a cancellation's cause lived only in the audit trail.
    op.execute(
        """
        UPDATE engagements e
        SET cancel_cause = 'esign_declined', declined_at = a.occurred_at
        FROM (
            SELECT target_id, max(occurred_at) AS occurred_at FROM audit_log
            WHERE target_type = 'engagement' AND action = 'engagement.contract_declined'
            GROUP BY target_id
        ) a
        WHERE e.id = a.target_id AND e.status = 'cancelled'
        """
    )
    unexplained = bind.execute(
        sa.text(
            """
            SELECT e.id FROM engagements e
            WHERE e.status = 'cancelled' AND e.cancel_cause IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM audit_log a
                WHERE a.target_type = 'engagement' AND a.target_id = e.id
                  AND a.action = 'engagement.cancelled' AND a.reason = 'worker_account_missing'
              )
            """
        )
    ).scalars()
    for engagement_id in unexplained:
        log.warning("cancelled engagement %s has no recorded cause", engagement_id)
    op.execute(
        "UPDATE engagements SET cancel_cause = 'worker_account_missing' "
        "WHERE status = 'cancelled' AND cancel_cause IS NULL"
    )

    for name, condition in _CHECKS.items():
        op.create_check_constraint(op.f(f"ck_engagements_{name}"), "engagements", condition)


def downgrade() -> None:
    for name in reversed(list(_CHECKS)):
        op.drop_constraint(op.f(f"ck_engagements_{name}"), "engagements", type_="check")
    for column in (
        "void_requested_at",
        "decline_note",
        "decline_reason",
        "declined_at",
        "cancel_cause",
    ):
        op.drop_column("engagements", column)
    op.execute("DROP TYPE declinereason")
    op.execute("DROP TYPE cancelcause")

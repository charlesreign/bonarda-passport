"""governance: policy_configs invariants (live ⇒ activated_at; immutable once proposed)

Revision ID: 0012_policy_guards
Revises: 0011_first_shot
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_policy_guards"
down_revision: str | None = "0011_first_shot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_policy_configs_activated_when_live"),
        "policy_configs",
        "status = 'draft' OR activated_at IS NOT NULL",
    )
    # NFR-5.1: a proposed rule set is the record of what was approved. Only
    # the status lifecycle and a draft's activation stamp may change. An
    # author or activator column may still become NULL (FK ON DELETE SET NULL).
    op.execute(
        """
        CREATE FUNCTION guard_policy_update() RETURNS trigger AS $$
        BEGIN
          IF NEW.kind IS DISTINCT FROM OLD.kind
             OR NEW.version IS DISTINCT FROM OLD.version
             OR NEW.rules IS DISTINCT FROM OLD.rules
             OR NEW.notes IS DISTINCT FROM OLD.notes
             OR (NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
                 AND NEW.created_by_id IS NOT NULL) THEN
            RAISE EXCEPTION 'policy_configs: a proposed policy is immutable';
          END IF;
          IF OLD.status <> 'draft'
             AND (NEW.activated_at IS DISTINCT FROM OLD.activated_at
                  OR (NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id
                      AND NEW.activated_by_id IS NOT NULL)) THEN
            RAISE EXCEPTION 'policy_configs: activation is immutable';
          END IF;
          IF NEW.status IS DISTINCT FROM OLD.status
             AND NOT ((OLD.status = 'draft' AND NEW.status = 'active')
                      OR (OLD.status = 'active' AND NEW.status = 'retired')) THEN
            RAISE EXCEPTION 'policy_configs: status cannot move from % to %',
              OLD.status, NEW.status;
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER policy_configs_guard BEFORE UPDATE ON policy_configs "
        "FOR EACH ROW EXECUTE FUNCTION guard_policy_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS policy_configs_guard ON policy_configs")
    op.execute("DROP FUNCTION IF EXISTS guard_policy_update()")
    op.drop_constraint(
        op.f("ck_policy_configs_activated_when_live"), "policy_configs", type_="check"
    )

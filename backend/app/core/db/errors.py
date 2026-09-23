from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint an asyncpg integrity error violated, so callers
    map exactly the violation they expect and re-raise everything else."""
    cause = getattr(exc.orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    return str(name) if name else None

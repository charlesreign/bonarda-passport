from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

import structlog

from app.core.enums import UserRole

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


@contextmanager
def correlation_scope(correlation_id: str | None) -> Iterator[None]:
    """Binds the correlation ID for audit rows, outbox events and log lines."""
    token = _correlation_id.set(correlation_id)
    try:
        with structlog.contextvars.bound_contextvars(correlation_id=correlation_id):
            yield
    finally:
        _correlation_id.reset(token)


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller. `worker_id` is set only for role WORKER."""

    user_id: UUID
    role: UserRole
    worker_id: UUID | None = None

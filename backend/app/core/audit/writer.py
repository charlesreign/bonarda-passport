from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.context import Actor, get_correlation_id


async def write_audit(
    session: AsyncSession,
    *,
    actor: Actor | None,
    action: str,
    target_type: str,
    target_id: UUID,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    """Adds an audit row to the caller's session. It commits with the change it
    describes — never call this on a different session from the domain write."""
    entry = AuditLog(
        actor_id=actor.user_id if actor else None,
        actor_role=actor.role.value if actor else "system",
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=dict(before) if before is not None else None,
        after=dict(after) if after is not None else None,
        reason=reason,
        correlation_id=get_correlation_id(),
    )
    session.add(entry)
    return entry

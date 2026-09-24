"""Ending a staff member's access (spec §7.6). SCIM and a role change seen at
OIDC login share this one path."""

from datetime import datetime
from typing import Literal

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import AccessGrantRepository, RefreshSessionRepository
from app.modules.identity.revocation import mark_revoked
from app.modules.identity.schemas import AccessRevoked

RevocationReason = Literal["deactivated", "role_changed"]

log = structlog.get_logger(__name__)


async def revoke_access(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    user: UserAccount,
    *,
    before: dict[str, str],
    reason: RevocationReason,
    marker_at: datetime,
) -> None:
    """Ends refresh sessions, marks access tokens issued before `marker_at`
    revoked, closes the user's open grants (FR-9.5), audits, and emits
    AccessRevoked, whose handler ends the user's project staffing."""
    now = utcnow()
    await RefreshSessionRepository(session).revoke_all_for_user(user.id, now, reason="admin")
    try:
        await mark_revoked(redis, settings, user.id, marker_at)
    except (RedisError, OSError):
        # The DB revocation (refresh sessions + status) is durable and commits
        # regardless; the marker only shortens the window during which an
        # already-issued access token keeps working, and the 10-min
        # access-token TTL already bounds that exposure (spec §8.1).
        log.error("auth.revocation_marker_unavailable", user_id=str(user.id))
    for grant in await AccessGrantRepository(session).list_open_for_grantee(user.id):
        grant.revoked_at = now
        await write_audit(
            session,
            actor=None,
            action="access_grant.revoked",
            target_type="access_grant",
            target_id=grant.id,
            before={"revoked_at": None},
            after={"revoked_at": grant.revoked_at.isoformat()},
            reason=reason,
        )
    await write_audit(
        session,
        actor=None,
        action="access.revoked",
        target_type="user_account",
        target_id=user.id,
        before=before,
        after={"status": user.status.value, "role": user.role.value},
        reason=reason,
    )
    await emit_event(session, AccessRevoked(aggregate_id=user.id, reason=reason))

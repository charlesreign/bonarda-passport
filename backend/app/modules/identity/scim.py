from dataclasses import dataclass
from typing import Any, Literal

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.errors import BadRequest, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import (
    AccessGrantRepository,
    RefreshSessionRepository,
    UserRepository,
)
from app.modules.identity.revocation import mark_revoked
from app.modules.identity.schemas import AccessRevoked, ScimPatch

log = structlog.get_logger(__name__)


@dataclass
class _Changes:
    active: bool | None = None
    role: UserRole | None = None


def _invalid(detail: str) -> BadRequest:
    return BadRequest(detail, code="scim_invalid_value")


def _parse_bool(value: Any) -> bool:
    # bool("False") is True — IdPs such as Azure AD send booleans as strings.
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise _invalid("'active' must be a boolean")


def _parse_role(value: Any) -> UserRole:
    try:
        return UserRole(value[0]["value"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise _invalid('\'roles\' must be a list like [{"value": "pm"}]') from exc


def _interpret(patch: ScimPatch) -> _Changes:
    changes = _Changes()
    for operation in patch.operations:
        if operation.op.lower() not in ("replace", "add"):
            continue
        if operation.path == "active":
            changes.active = _parse_bool(operation.value)
        elif operation.path == "roles":
            changes.role = _parse_role(operation.value)
        elif operation.path is None and isinstance(operation.value, dict):
            if "active" in operation.value:
                changes.active = _parse_bool(operation.value["active"])
            if "roles" in operation.value:
                changes.role = _parse_role(operation.value["roles"])
    return changes


class ScimService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.users = UserRepository(session)
        self.refresh = RefreshSessionRepository(session)
        self.grants = AccessGrantRepository(session)

    async def patch_user(self, subject: str, patch: ScimPatch) -> UserAccount:
        user = await self.users.get_by_oidc_subject(subject)
        if user is None:
            raise NotFound("No account for this SCIM id", code="scim_user_not_found")
        changes = _interpret(patch)
        before = {"status": user.status.value, "role": user.role.value}
        reason: Literal["deactivated", "role_changed"] | None = None

        if changes.active is False and user.status is AccountStatus.ACTIVE:
            user.status = AccountStatus.REVOKED
            reason = "deactivated"
        elif changes.active is True and user.status is AccountStatus.REVOKED:
            user.status = AccountStatus.ACTIVE
            await write_audit(
                self.session,
                actor=None,
                action="user.reactivated",
                target_type="user_account",
                target_id=user.id,
                before=before,
                after={"status": user.status.value, "role": user.role.value},
                reason="scim",
            )
        if changes.role is not None and changes.role is not user.role:
            user.role = changes.role
            if reason is None:
                reason = "role_changed"

        if reason is not None:
            await self._revoke(user, before, reason)
        return user

    async def _revoke(
        self,
        user: UserAccount,
        before: dict[str, str],
        reason: Literal["deactivated", "role_changed"],
    ) -> None:
        now = utcnow()
        await self.refresh.revoke_all_for_user(user.id, now)
        try:
            await mark_revoked(self.redis, self.settings, user.id, now)
        except (RedisError, OSError):
            # The DB revocation (refresh sessions + status) is durable and
            # commits regardless; the marker only shortens the window during
            # which an already-issued access token keeps working, and the
            # 10-min access-token TTL already bounds that exposure (spec
            # Section 8.1).
            log.error("auth.revocation_marker_unavailable", user_id=str(user.id))
        # FR-9.5/spec Section 7.6-7.7: a PM's own access no longer being valid
        # must also close whatever detail-visibility grants they were given —
        # otherwise a PM stays able to see a worker's file after deactivation.
        for grant in await self.grants.list_open_for_grantee(user.id):
            grant.revoked_at = now
            await write_audit(
                self.session,
                actor=None,
                action="access_grant.revoked",
                target_type="access_grant",
                target_id=grant.id,
                before={"revoked_at": None},
                after={"revoked_at": grant.revoked_at.isoformat()},
                reason=reason,
            )
        await write_audit(
            self.session,
            actor=None,
            action="access.revoked",
            target_type="user_account",
            target_id=user.id,
            before=before,
            after={"status": user.status.value, "role": user.role.value},
            reason=reason,
        )
        await emit_event(self.session, AccessRevoked(aggregate_id=user.id, reason=reason))

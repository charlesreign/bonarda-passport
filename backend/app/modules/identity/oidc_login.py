import json
import secrets
from datetime import timedelta
from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.errors import BadRequest, Conflict, Forbidden
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import UserAccount
from app.modules.identity.oidc import IdTokenClaims, OidcProvider
from app.modules.identity.repository import (
    RefreshSessionRepository,
    UserRepository,
    normalize_email,
)
from app.modules.identity.revocation import mark_revoked
from app.modules.identity.schemas import AccessRevoked

STATE_PREFIX = "oidc:state:"
STATE_TTL_SECONDS = 600
ROLE_PRECEDENCE = (UserRole.ADMIN, UserRole.PEOPLE_OPS, UserRole.FINANCE, UserRole.PM)

log = structlog.get_logger(__name__)


class OidcLoginService:
    def __init__(
        self, session: AsyncSession, redis: Redis, settings: Settings, provider: OidcProvider
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.provider = provider
        self.users = UserRepository(session)

    async def begin(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(48)
        await self.redis.set(
            STATE_PREFIX + state,
            json.dumps({"nonce": nonce, "code_verifier": code_verifier}),
            ex=STATE_TTL_SECONDS,
        )
        url = await self.provider.authorization_url(
            state=state, nonce=nonce, code_verifier=code_verifier
        )
        return url, state

    async def complete(self, *, code: str, state: str) -> tuple[UserAccount, IdTokenClaims]:
        raw = await self.redis.getdel(STATE_PREFIX + state)
        if raw is None:
            raise BadRequest("Sign-in session expired; start again", code="oidc_state_invalid")
        pending = json.loads(raw)
        claims = await self.provider.exchange_code(
            code=code, code_verifier=pending["code_verifier"], nonce=pending["nonce"]
        )
        self._require_mfa(claims)
        role = self._role_for(claims.groups)
        return await self._upsert(claims, role), claims

    def _require_mfa(self, claims: IdTokenClaims) -> None:
        amr_ok = bool(set(claims.amr) & set(self.settings.oidc_required_amr))
        acr_ok = claims.acr is not None and claims.acr in self.settings.oidc_accepted_acr
        if not (amr_ok or acr_ok):
            raise Forbidden("Multi-factor authentication is required", code="mfa_required")

    def _role_for(self, groups: list[str]) -> UserRole:
        mapping = self.settings.oidc_group_role_map
        roles = {mapping[g] for g in groups if g in mapping}
        for role in ROLE_PRECEDENCE:
            if role in roles:
                return role
        raise Forbidden("No Bonarda role is assigned to this account", code="no_role_assigned")

    async def _upsert(self, claims: IdTokenClaims, role: UserRole) -> UserAccount:
        user = await self.users.get_by_oidc_subject(claims.subject)
        if user is None:
            if not claims.email:
                raise Forbidden("The identity provider sent no email", code="email_missing")
            if await self.users.get_by_email(claims.email) is not None:
                raise Conflict("Email already belongs to another account", code="email_conflict")
            user = self.users.add(
                UserAccount(
                    email=normalize_email(claims.email),
                    role=role,
                    auth_provider=AuthProvider.CORPORATE_SSO,
                    oidc_subject=claims.subject,
                )
            )
            await self.session.flush()  # assigns user.id for the audit row
            await write_audit(
                self.session,
                actor=None,
                action="user.provisioned",
                target_type="user_account",
                target_id=user.id,
                after={"email": user.email, "role": role.value},
            )
            return user
        if user.status is not AccountStatus.ACTIVE:
            raise Forbidden("This account has been deactivated", code="account_inactive")
        if user.role is not role:
            previous = user.role
            user.role = role
            await write_audit(
                self.session,
                actor=None,
                action="user.role_changed",
                target_type="user_account",
                target_id=user.id,
                before={"role": previous.value},
                after={"role": role.value},
                reason="idp_group_membership",
            )
            await RefreshSessionRepository(self.session).revoke_all_for_user(
                user.id, utcnow(), reason="admin"
            )
            await self._mark_revoked_quietly(user.id)
            # Same as a SCIM role change: staffing ends (spec §7.6).
            await emit_event(
                self.session, AccessRevoked(aggregate_id=user.id, reason="role_changed")
            )
        return user

    async def _mark_revoked_quietly(self, user_id: UUID) -> None:
        # One second in the past: tokens from before this login stop working,
        # while the session this login is about to issue stays valid.
        try:
            await mark_revoked(self.redis, self.settings, user_id, utcnow() - timedelta(seconds=1))
        except (RedisError, OSError):
            log.error("auth.revocation_marker_unavailable", user_id=str(user_id))

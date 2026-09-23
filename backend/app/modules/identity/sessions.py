from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow
from app.modules.identity.models import RefreshSession, UserAccount
from app.modules.identity.repository import RefreshSessionRepository, UserRepository
from app.modules.identity.tokens import hash_token, issue_access_token, new_opaque_token

# Two tabs refreshing together present the same token twice. Inside this window
# the loser gets a retryable 401 instead of triggering theft detection.
REUSE_GRACE = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_max_age: int


class SessionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.refresh = RefreshSessionRepository(session)

    def _limits(self, role: UserRole) -> tuple[timedelta, timedelta]:
        s = self.settings
        if role is UserRole.WORKER:
            return (
                timedelta(seconds=s.worker_idle_timeout_seconds),
                timedelta(seconds=s.worker_session_max_seconds),
            )
        return (
            timedelta(seconds=s.staff_idle_timeout_seconds),
            timedelta(seconds=s.staff_session_max_seconds),
        )

    def _issue(
        self, user: UserAccount, *, family_id: UUID, started: datetime, amr: list[str]
    ) -> IssuedSession:
        now = utcnow()
        idle, cap = self._limits(user.role)
        expires_at = min(now + idle, started + cap)
        refresh_token = new_opaque_token()
        self.refresh.add(
            RefreshSession(
                user_id=user.id,
                family_id=family_id,
                family_started_at=started,
                token_hash=hash_token(refresh_token),
                amr=amr,
                expires_at=expires_at,
            )
        )
        access = issue_access_token(
            self.settings, user_id=user.id, role=user.role, worker_id=user.worker_id, amr=amr
        )
        return IssuedSession(
            access_token=access,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_ttl_seconds,
            refresh_max_age=int((expires_at - now).total_seconds()),
        )

    async def start(self, user: UserAccount, *, amr: list[str]) -> IssuedSession:
        now = utcnow()
        user.last_login_at = now
        return self._issue(user, family_id=uuid4(), started=now, amr=amr)

    async def rotate(self, refresh_token: str) -> IssuedSession:
        now = utcnow()
        current = await self.refresh.get_by_hash_for_update(hash_token(refresh_token))
        if current is None:
            raise Unauthorized("Unknown refresh token", code="invalid_refresh")
        if current.revoked_at is not None:
            if current.revoked_reason != "rotated":
                # Logout, SCIM/admin revocation, or a family already flagged
                # for reuse — not an ordinary rotation. Presenting this token
                # again isn't theft, it's stale; treat it as ended, with no
                # audit row and no (further) family revocation.
                raise Unauthorized("Session has ended", code="session_revoked")
            if now - current.revoked_at <= REUSE_GRACE:
                raise Unauthorized(
                    "Session was refreshed elsewhere; retry", code="refresh_superseded"
                )
            await self.refresh.revoke_family(current.family_id, now, reason="reuse")
            await write_audit(
                self.session,
                actor=None,
                action="auth.refresh_reuse_detected",
                target_type="user_account",
                target_id=current.user_id,
                after={"family_id": str(current.family_id)},
            )
            # Commit before raising: the error response must not roll back the
            # revocation, or a stolen token family would stay usable.
            await self.session.commit()
            raise Unauthorized("Refresh token reuse detected", code="refresh_reuse_detected")
        if current.expires_at <= now:
            raise Unauthorized("Session expired", code="session_expired")
        user = await self.users.get(current.user_id)
        if user is None or user.status is not AccountStatus.ACTIVE:
            raise Unauthorized("Account is not active", code="account_inactive")
        current.revoked_at = now
        current.revoked_reason = "rotated"
        return self._issue(
            user, family_id=current.family_id, started=current.family_started_at, amr=current.amr
        )

    async def end(self, refresh_token: str) -> None:
        current = await self.refresh.get_by_hash(hash_token(refresh_token))
        if current is not None:
            await self.refresh.revoke_family(current.family_id, utcnow(), reason="logout")
            await write_audit(
                self.session,
                actor=None,
                action="auth.logout",
                target_type="user_account",
                target_id=current.user_id,
                after={"family_id": str(current.family_id)},
            )

from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.context import Actor
from app.core.enums import AccountStatus, UserRole
from app.core.errors import TooManyRequests, Unauthorized
from app.core.i18n import t
from app.core.mail import Mailer
from app.modules.identity.accounts import request_sign_in_link
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import UserRepository, normalize_email
from app.modules.identity.tokens import hash_token, new_opaque_token

TOKEN_PREFIX = "magiclink:"
# i18n key prefix per purpose; Task 8 adds "invitation".
_TEMPLATES = {"sign_in": "magic_link"}
log = structlog.get_logger(__name__)


def _eligible(user: UserAccount | None) -> bool:
    return user is not None and user.role is UserRole.WORKER and user.status is AccountStatus.ACTIVE


class MagicLinkService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.users = UserRepository(session)

    async def request(self, email: str, client_ip: str) -> None:
        """Behaves the same whether or not the email exists, so the endpoint
        cannot be used to discover who works with Bonarda. The link itself is
        issued and mailed by the worker (send_magic_link)."""
        email = normalize_email(email)
        s = self.settings
        await self._limit(f"ml:rate:email:{hash_token(email)}", s.magic_link_per_email_per_hour)
        await self._limit(f"ml:rate:ip:{client_ip}", s.magic_link_per_ip_per_hour)
        user = await self.users.get_by_email(email)
        if user is None or not _eligible(user):
            log.info("auth.magic_link_not_sent")
            return
        await request_sign_in_link(self.session, user.id, purpose="sign_in")

    async def _limit(self, key: str, limit: int) -> None:
        # SET NX (only if absent) then INCR in one MULTI/EXEC: the key always
        # carries a TTL from the moment it is created.
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(key, 0, ex=3600, nx=True)
            pipe.incr(key)
            _, count = await pipe.execute()
        if count > limit:
            raise TooManyRequests(
                "Too many sign-in link requests; try again later", code="magic_link_rate_limited"
            )

    async def verify(self, token: str) -> UserAccount:
        invalid = Unauthorized(
            "This sign-in link is invalid or has expired", code="magic_link_invalid"
        )
        user_id = await self.redis.getdel(TOKEN_PREFIX + hash_token(token))
        if user_id is None:
            raise invalid
        user = await self.users.get(UUID(user_id))
        if user is None or user.status is not AccountStatus.ACTIVE:
            raise invalid
        await write_audit(
            self.session,
            actor=Actor(user_id=user.id, role=user.role, worker_id=user.worker_id),
            action="auth.magic_link_login",
            target_type="user_account",
            target_id=user.id,
        )
        return user


async def send_magic_link(
    session: AsyncSession,
    *,
    redis: Redis,
    settings: Settings,
    mailer: Mailer,
    user_id: UUID,
    purpose: str,
) -> bool:
    """Runs in the worker (outbox handler). Re-checks eligibility, because the
    account may have changed since the request was queued."""
    user = await UserRepository(session).get(user_id)
    if user is None or not _eligible(user):
        log.info("auth.magic_link_skipped", user_id=str(user_id))
        return False
    token = new_opaque_token()
    await redis.set(
        TOKEN_PREFIX + hash_token(token), str(user.id), ex=settings.magic_link_ttl_seconds
    )
    # The token travels in the URL fragment so it never reaches server logs.
    link = f"{settings.public_app_url}/auth/verify#token={token}"
    prefix = _TEMPLATES[purpose]
    params = {
        "minutes": settings.magic_link_ttl_seconds // 60,
        "link": link,
        "sign_in_url": f"{settings.public_app_url}/sign-in",
    }
    await mailer.send(
        to=user.email,
        subject=t(f"{prefix}.subject", user.locale),
        body=t(f"{prefix}.body", user.locale, **params),
    )
    return True

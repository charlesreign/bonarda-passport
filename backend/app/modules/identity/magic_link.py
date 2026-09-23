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
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import UserRepository, normalize_email
from app.modules.identity.tokens import hash_token, new_opaque_token

TOKEN_PREFIX = "magiclink:"
log = structlog.get_logger(__name__)


class MagicLinkService:
    def __init__(
        self, session: AsyncSession, redis: Redis, settings: Settings, mailer: Mailer
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.mailer = mailer
        self.users = UserRepository(session)

    async def request(self, email: str, client_ip: str) -> None:
        """Always behaves the same whether or not the email exists, so the
        endpoint cannot be used to discover who works with Bonarda."""
        email = normalize_email(email)
        s = self.settings
        await self._limit(f"ml:rate:email:{hash_token(email)}", s.magic_link_per_email_per_hour)
        await self._limit(f"ml:rate:ip:{client_ip}", s.magic_link_per_ip_per_hour)
        user = await self.users.get_by_email(email)
        if (
            user is None
            or user.role is not UserRole.WORKER
            or user.status is not AccountStatus.ACTIVE
        ):
            log.info("auth.magic_link_not_sent")
            return
        token = new_opaque_token()
        await self.redis.set(
            TOKEN_PREFIX + hash_token(token), str(user.id), ex=s.magic_link_ttl_seconds
        )
        # The token travels in the URL fragment so it never reaches server logs.
        link = f"{s.public_app_url}/auth/verify#token={token}"
        minutes = s.magic_link_ttl_seconds // 60
        await self.mailer.send(
            to=user.email,
            subject=t("magic_link.subject"),
            body=t("magic_link.body", minutes=minutes, link=link),
        )

    async def _limit(self, key: str, limit: int) -> None:
        # SET NX (only if absent) then INCR, both in one MULTI/EXEC pipeline:
        # the key always carries a TTL from the moment it's created. The
        # previous "INCR, then EXPIRE if this was the first hit" sequence had
        # a window where a crash between the two left the key without a TTL,
        # making the limit permanent instead of hourly.
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

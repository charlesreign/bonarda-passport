from datetime import datetime
from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

log = structlog.get_logger(__name__)


def _key(user_id: UUID) -> str:
    return f"revoked_after:{user_id}"


async def mark_revoked(redis: Redis, settings: Settings, user_id: UUID, at: datetime) -> None:
    """Tokens issued at or before `at` stop working immediately. The marker only
    needs to outlive the longest access token, so it expires on its own."""
    await redis.set(
        _key(user_id), str(int(at.timestamp())), ex=settings.revocation_marker_ttl_seconds
    )


async def is_revoked(redis: Redis, user_id: UUID, issued_at: datetime) -> bool:
    """Fails open: if Redis is unreachable the 10-minute token TTL still bounds
    revocation within the 15-minute NFR-3.5 target (spec §8.1)."""
    try:
        raw = await redis.get(_key(user_id))
    except (RedisError, OSError):
        log.warning("auth.revocation_check_unavailable", user_id=str(user_id))
        return False
    return raw is not None and int(issued_at.timestamp()) <= int(raw)

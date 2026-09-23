from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.identity.magic_link import send_magic_link
from app.modules.identity.schemas import MagicLinkRequested


def register(
    registry: HandlerRegistry, *, redis: Redis, settings: Settings, mailer: Mailer
) -> None:
    async def send_link(session: AsyncSession, payload: dict[str, Any]) -> None:
        await send_magic_link(
            session,
            redis=redis,
            settings=settings,
            mailer=mailer,
            user_id=UUID(payload["aggregate_id"]),
            purpose=payload.get("purpose", "sign_in"),
        )

    registry.register(MagicLinkRequested, "identity.send_magic_link", send_link)

from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.core.time import utcnow
from app.modules.identity.accounts import delete_worker_account
from app.modules.identity.magic_link import send_magic_link
from app.modules.identity.revocation import mark_revoked
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

    async def delete_account(session: AsyncSession, payload: dict[str, Any]) -> None:
        user_id = await delete_worker_account(session, UUID(payload["aggregate_id"]))
        if user_id is not None:
            # Tokens already issued stop working at once, not at expiry.
            await mark_revoked(redis, settings, user_id, utcnow())

    # By event type: identity does not import passport.
    registry.register(
        "passport.worker_anonymized", "identity.delete_worker_account", delete_account
    )

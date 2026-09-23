"""Composition root: the only place that knows every module's handlers and
visibility sources, and what each handler needs to run."""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.identity import handlers as identity_handlers
from app.modules.identity.service import VisibilitySource


@dataclass(frozen=True, slots=True)
class HandlerDeps:
    settings: Settings
    redis: Redis
    mailer: Mailer


def build_registry(deps: HandlerDeps) -> HandlerRegistry:
    registry = HandlerRegistry()
    identity_handlers.register(
        registry, redis=deps.redis, settings=deps.settings, mailer=deps.mailer
    )
    return registry


def visibility_sources() -> list[VisibilitySource]:
    return []

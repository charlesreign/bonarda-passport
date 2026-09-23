"""Composition root: the only place that knows every module's handlers and
visibility sources, and what each handler needs to run."""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements import handlers as engagements_handlers
from app.modules.engagements.service import project_relationship
from app.modules.identity import handlers as identity_handlers
from app.modules.identity.service import VisibilitySource
from app.modules.integrations.service import EsignAdapter, PayrollAdapter


@dataclass(frozen=True, slots=True)
class HandlerDeps:
    settings: Settings
    redis: Redis
    mailer: Mailer
    esign: EsignAdapter
    payroll: PayrollAdapter


def build_registry(deps: HandlerDeps) -> HandlerRegistry:
    registry = HandlerRegistry()
    identity_handlers.register(
        registry, redis=deps.redis, settings=deps.settings, mailer=deps.mailer
    )
    engagements_handlers.register(registry)
    return registry


def visibility_sources() -> list[VisibilitySource]:
    return [project_relationship]

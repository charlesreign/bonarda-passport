"""Composition root: the only place that knows every module's handlers and
visibility sources, and what each handler needs to run."""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.mail import Mailer
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements import handlers as engagements_handlers
from app.modules.engagements.service import (
    engagement_worker_id,
    feedback_worker_id,
    project_relationship,
)
from app.modules.governance import handlers as governance_handlers
from app.modules.governance.service import DisputeTargetType, TargetOwner
from app.modules.identity import handlers as identity_handlers
from app.modules.identity.service import VisibilitySource
from app.modules.integrations.service import EsignAdapter, PayrollAdapter
from app.modules.roster import handlers as roster_handlers
from app.modules.roster.service import first_shot_relationship
from app.modules.standing import handlers as standing_handlers
from app.modules.standing.service import standing_change_worker_id


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
    engagements_handlers.register(
        registry, esign=deps.esign, payroll=deps.payroll, mailer=deps.mailer
    )
    standing_handlers.register(registry, mailer=deps.mailer)
    governance_handlers.register(registry, mailer=deps.mailer)
    roster_handlers.register(registry)
    return registry


def visibility_sources() -> list[VisibilitySource]:
    return [project_relationship, first_shot_relationship]


def dispute_target_owners() -> dict[DisputeTargetType, TargetOwner]:
    """Who owns each kind of disputable record. governance imports no domain
    module, so the composition root supplies these lookups."""
    return {
        DisputeTargetType.FEEDBACK: feedback_worker_id,
        DisputeTargetType.STANDING_CHANGE: standing_change_worker_id,
        DisputeTargetType.ENGAGEMENT: engagement_worker_id,
    }

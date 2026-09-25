from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.events import DomainEvent
from app.core.outbox.registry import HandlerRegistry
from app.modules.engagements.schemas import (
    ContractSigned,
    EngagementActivated,
    EngagementCancelled,
    EngagementCompleted,
    EngagementCreated,
)
from app.modules.engagements.service import engagement_worker_id
from app.modules.passport.schemas import (
    ConsentChanged,
    WorkerAnonymized,
    WorkerInvited,
    WorkerUpdated,
)
from app.modules.roster.first_shot import mark_first_shot_engaged
from app.modules.roster.refresh import refresh_worker
from app.modules.standing.schemas import SkillVerified, StandingChanged

# aggregate_id is the worker.
_WORKER_EVENTS: tuple[type[DomainEvent], ...] = (
    WorkerInvited,
    WorkerUpdated,
    WorkerAnonymized,
    ConsentChanged,
    StandingChanged,
    SkillVerified,
)
# The payload carries worker_id.
_ENGAGEMENT_EVENTS: tuple[type[DomainEvent], ...] = (
    EngagementActivated,
    EngagementCompleted,
    EngagementCancelled,
)


def register(registry: HandlerRegistry) -> None:
    async def by_aggregate(session: AsyncSession, payload: dict[str, Any]) -> None:
        await refresh_worker(session, UUID(payload["aggregate_id"]))

    async def by_worker_field(session: AsyncSession, payload: dict[str, Any]) -> None:
        await refresh_worker(session, UUID(payload["worker_id"]))

    async def by_engagement(session: AsyncSession, payload: dict[str, Any]) -> None:
        worker_id = await engagement_worker_id(session, UUID(payload["aggregate_id"]))
        if worker_id is not None:
            await refresh_worker(session, worker_id)

    for event in _WORKER_EVENTS:
        registry.register(event, f"roster.refresh_worker:{event.event_type}", by_aggregate)
    for event in _ENGAGEMENT_EVENTS:
        registry.register(event, f"roster.refresh_worker:{event.event_type}", by_worker_field)
    registry.register(
        ContractSigned, f"roster.refresh_worker:{ContractSigned.event_type}", by_engagement
    )

    async def first_shot_engaged(session: AsyncSession, payload: dict[str, Any]) -> None:
        await mark_first_shot_engaged(
            session, UUID(payload["project_id"]), UUID(payload["worker_id"])
        )

    registry.register(EngagementCreated, "roster.mark_first_shot_engaged", first_shot_engaged)

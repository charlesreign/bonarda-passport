from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.context import Actor
from app.core.errors import Forbidden
from app.modules.identity.service import Permission, require_permission


@dataclass(frozen=True, slots=True)
class WorkerActor:
    """A worker acting on their own passport."""

    actor: Actor
    worker_id: UUID


def _worker_self(permission: Permission) -> Callable[..., Awaitable[WorkerActor]]:
    async def dependency(
        actor: Annotated[Actor, Depends(require_permission(permission))],
    ) -> WorkerActor:
        if actor.worker_id is None:
            raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
        return WorkerActor(actor=actor, worker_id=actor.worker_id)

    return dependency


WorkerReader = Annotated[WorkerActor, Depends(_worker_self(Permission.WORKER_READ_SELF))]
WorkerEditor = Annotated[WorkerActor, Depends(_worker_self(Permission.WORKER_UPDATE_SELF))]

from collections.abc import Awaitable, Callable, Sequence
from enum import IntEnum
from typing import Annotated, get_args, get_origin
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.enums import UserRole
from app.core.errors import NotFound
from app.core.time import utcnow
from app.modules.identity.dependencies import CurrentActor
from app.modules.identity.repository import AccessGrantRepository


class Visibility(IntEnum):
    NONE = 0
    SUMMARY = 1  # search card (spec §7.1)
    DETAIL = 2  # history, feedback, standing factors, disputes
    SELF = 3  # the worker looking at their own passport


VisibilitySource = Callable[[AsyncSession, Actor, UUID], Awaitable[Visibility]]
# Whether PMs may see this worker at all (False once anonymized/offboarded).
SurfacedCheck = Callable[[AsyncSession, UUID], Awaitable[bool]]


class VisibilityPolicy:
    """The single enforcement point for who may see which worker (FR-9.4).
    Relationship rules owned by other modules (engaged on my project,
    shortlisted for my project) plug in as sources via app.wiring."""

    def __init__(
        self, sources: Sequence[VisibilitySource] = (), surfaced: SurfacedCheck | None = None
    ) -> None:
        self._sources = tuple(sources)
        self._surfaced = surfaced

    async def level(self, session: AsyncSession, actor: Actor, worker_id: UUID) -> Visibility:
        if actor.role is UserRole.WORKER:
            return Visibility.SELF if actor.worker_id == worker_id else Visibility.NONE
        if actor.role in (UserRole.PEOPLE_OPS, UserRole.ADMIN):
            return Visibility.DETAIL
        if actor.role is not UserRole.PM:
            return Visibility.NONE
        # Spec §6.3: after erasure only structural history remains, for People
        # Ops. No past relationship or grant keeps a PM's view of the person.
        if self._surfaced is not None and not await self._surfaced(session, worker_id):
            return Visibility.NONE
        if await AccessGrantRepository(session).has_active(actor.user_id, worker_id, utcnow()):
            return Visibility.DETAIL
        best = Visibility.NONE
        for source in self._sources:
            best = max(best, await source(session, actor, worker_id))
            if best >= Visibility.DETAIL:
                break
        return best


def get_visibility_policy(request: Request) -> VisibilityPolicy:
    return request.app.state.visibility_policy


GUARD_MARKER = "__bonarda_visibility_guard__"


def require_visibility(minimum: Visibility) -> Callable[..., Awaitable[Visibility]]:
    """Route dependency for anything addressed by `worker_id`. Below the
    minimum it answers 404, so callers cannot probe which workers exist."""

    async def dependency(
        worker_id: UUID,
        actor: CurrentActor,
        session: SessionDep,
        policy: Annotated[VisibilityPolicy, Depends(get_visibility_policy)],
    ) -> Visibility:
        level = await policy.level(session, actor, worker_id)
        if level < minimum:
            raise NotFound("Worker not found", code="worker_not_found")
        return level

    setattr(dependency, GUARD_MARKER, True)
    return dependency


def _has_guard(dependant: Dependant) -> bool:
    return any(
        getattr(sub.call, GUARD_MARKER, False) or _has_guard(sub) for sub in dependant.dependencies
    )


def _field_names_in(annotation: object, seen: set[type]) -> set[str]:
    """Recursively collect field names reachable from a type annotation:
    through Annotated[...], Optional/Union (typing.Union and X | Y), and
    generic containers (list, set, tuple, dict, Sequence, ...), into any
    BaseModel found along the way. `seen` guards self-referential models."""
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return _field_names_in(args[0], seen) if args else set()
    if origin is not None:
        names: set[str] = set()
        for arg in get_args(annotation):
            names |= _field_names_in(arg, seen)
        return names
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return set()
        seen = seen | {annotation}
        names = set(annotation.model_fields)
        for field in annotation.model_fields.values():
            names |= _field_names_in(field.annotation, seen)
        return names
    return set()


def _body_field_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    for param in get_flat_dependant(route.dependant).body_params:
        names.add(param.name)
        names |= _field_names_in(param.field_info.annotation, set())
    return names


def unguarded_worker_routes(app: FastAPI) -> list[str]:
    """Routes that could expose a worker without the visibility check: a
    `worker_id` path/query parameter without require_visibility, or a
    `worker_id` anywhere in a request body (address workers in the path)."""
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        flat = get_flat_dependant(route.dependant)
        params = {p.name for p in flat.path_params + flat.query_params}
        unguarded_param = "worker_id" in params and not _has_guard(route.dependant)
        if unguarded_param or "worker_id" in _body_field_names(route):
            offenders.append(route.path)
    return offenders

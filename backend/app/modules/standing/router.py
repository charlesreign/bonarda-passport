from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.core.errors import Forbidden
from app.modules.identity.service import (
    CurrentActor,
    Permission,
    Visibility,
    require_permission,
    require_visibility,
)
from app.modules.standing.explanation import standing_explanation
from app.modules.standing.overrides import override_standing
from app.modules.standing.schemas import (
    StandingChangeRead,
    StandingExplanation,
    StandingOverrideCreate,
)

router = APIRouter(prefix="/api/v1", tags=["standing"])

StandingOverrider = Annotated[Actor, Depends(require_permission(Permission.STANDING_OVERRIDE))]


@router.get("/workers/me/standing")
async def my_standing(actor: CurrentActor, session: SessionDep) -> StandingExplanation:
    if actor.worker_id is None:
        raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
    return await standing_explanation(session, actor.worker_id)


@router.get("/workers/{worker_id}/standing")
async def worker_standing(
    worker_id: UUID,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> StandingExplanation:
    return await standing_explanation(session, worker_id)


@router.post("/workers/{worker_id}/standing-overrides", status_code=201)
async def override_worker_standing(
    worker_id: UUID,
    body: StandingOverrideCreate,
    actor: StandingOverrider,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.DETAIL))],
) -> StandingChangeRead:
    change = await override_standing(session, actor, worker_id, body)
    return StandingChangeRead(
        id=change.id,
        previous_tier=change.previous_tier,
        new_tier=change.new_tier,
        factors=change.contributing_factors,
        policy_version=change.contributing_factors["policy_version"],
        automated=False,
        override_reason=change.override_reason,
        occurred_at=change.created_at,
    )

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db.session import SessionDep
from app.core.errors import Forbidden
from app.modules.identity.service import CurrentActor, Visibility, require_visibility
from app.modules.standing.explanation import standing_explanation
from app.modules.standing.schemas import StandingExplanation

router = APIRouter(prefix="/api/v1", tags=["standing"])


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

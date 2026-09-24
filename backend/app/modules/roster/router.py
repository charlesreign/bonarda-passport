from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.identity.service import (
    Permission,
    Visibility,
    require_permission,
    require_visibility,
)
from app.modules.passport.service import AvailabilityStatus
from app.modules.roster.candidates import CandidateFilters, search
from app.modules.roster.first_shot import first_shot_panel, review
from app.modules.roster.schemas import (
    CandidatePage,
    FirstShotPanel,
    FirstShotReviewCreate,
    FirstShotReviewRead,
)

router = APIRouter(prefix="/api/v1", tags=["roster"])

RosterSearcher = Annotated[Actor, Depends(require_permission(Permission.ROSTER_SEARCH))]
FirstShotReviewer = Annotated[Actor, Depends(require_permission(Permission.FIRST_SHOT_REVIEW))]


@router.get("/projects/{project_id}/candidates")
async def list_candidates(
    project_id: UUID,
    actor: RosterSearcher,
    session: SessionDep,
    skill_ids: Annotated[list[UUID] | None, Query(max_length=20)] = None,
    availability: AvailabilityStatus | None = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CandidatePage:
    filters = CandidateFilters(
        skill_ids=tuple(skill_ids or ()),
        availability=availability.value if availability else None,
        location=location,
        q=q,
    )
    return await search(session, actor, project_id, filters, cursor, limit)


@router.get("/projects/{project_id}/first-shot")
async def get_first_shot(
    project_id: UUID, actor: FirstShotReviewer, session: SessionDep
) -> FirstShotPanel:
    return await first_shot_panel(session, actor, project_id)


@router.post("/projects/{project_id}/first-shot/{worker_id}/review")
async def review_first_shot(
    project_id: UUID,
    worker_id: UUID,
    body: FirstShotReviewCreate,
    actor: FirstShotReviewer,
    session: SessionDep,
    level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
) -> FirstShotReviewRead:
    return FirstShotReviewRead.model_validate(
        await review(session, actor, project_id, worker_id, body)
    )

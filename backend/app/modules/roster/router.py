from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.context import Actor
from app.core.db.session import SessionDep
from app.modules.identity.service import Permission, require_permission
from app.modules.passport.service import AvailabilityStatus
from app.modules.roster.candidates import CandidateFilters, search
from app.modules.roster.schemas import CandidatePage

router = APIRouter(prefix="/api/v1", tags=["roster"])

RosterSearcher = Annotated[Actor, Depends(require_permission(Permission.ROSTER_SEARCH))]


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

"""Scored candidate search over the roster (spec §7.1, §7.4, §8.5)."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.errors import BadRequest, NotFound
from app.core.time import utcnow
from app.modules.engagements.schemas import ProjectContext
from app.modules.engagements.service import staffed_project
from app.modules.governance.service import active_matching
from app.modules.roster.models import RosterProfile
from app.modules.roster.repository import RosterRepository
from app.modules.roster.schemas import Candidate, CandidateCard, CandidatePage, ScoreBreakdown
from app.modules.roster.scoring import ProjectNeeds, rank


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    skill_ids: tuple[UUID, ...] = ()
    availability: str | None = None
    location: str | None = None
    q: str | None = None


def project_needs(project: ProjectContext, today: date) -> ProjectNeeds:
    """A project's start is `max(starts_on or today, today)`: a project that
    has already started needs people now."""
    starts_on = max(project.starts_on or today, today)
    return ProjectNeeds(
        required_skill_ids=frozenset(project.required_skill_ids), starts_on=starts_on
    )


def card(profile: RosterProfile) -> CandidateCard:
    verified = set(profile.verified_skill_ids)
    return CandidateCard(
        worker_id=profile.worker_id,
        display_name=profile.display_name,
        standing_tier=profile.standing_tier,
        verified_skill_ids=sorted(verified, key=str),
        self_reported_skill_ids=sorted(set(profile.skill_ids) - verified, key=str),
        availability_status=profile.availability_status,
        available_from=profile.available_from,
        base_location=profile.base_location,
        engagements_total=profile.engagements_total,
    )


def _encode(breakdown: ScoreBreakdown, profile: RosterProfile) -> str:
    raw = json.dumps({"s": breakdown.total, "w": str(profile.worker_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode(cursor: str) -> tuple[float, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return float(data["s"]), str(UUID(data["w"]))
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise BadRequest("Invalid cursor", code="invalid_cursor") from exc


async def visible_project(session: AsyncSession, actor: Actor, project_id: UUID) -> ProjectContext:
    project = await staffed_project(session, actor.user_id, project_id)
    if project is None:
        raise NotFound("Project not found", code="project_not_found")
    return project


async def search(
    session: AsyncSession,
    actor: Actor,
    project_id: UUID,
    filters: CandidateFilters,
    cursor: str | None,
    limit: int,
) -> CandidatePage:
    project = await visible_project(session, actor, project_id)
    policy = await active_matching(session)
    profiles = await RosterRepository(session).eligible(
        project.data_region,
        skill_ids=filters.skill_ids,
        availability=filters.availability,
        location=filters.location,
        q=filters.q,
    )
    ranked = rank(profiles, project_needs(project, utcnow().date()), policy)
    if cursor is not None:
        after_total, after_worker = _decode(cursor)
        ranked = [
            (b, p) for b, p in ranked if (-b.total, str(p.worker_id)) > (-after_total, after_worker)
        ]
    page = ranked[:limit]
    return CandidatePage(
        items=[Candidate(worker=card(p), score=b.total, score_breakdown=b) for b, p in page],
        next_cursor=_encode(*page[-1]) if len(ranked) > limit else None,
    )

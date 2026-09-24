import hashlib
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.errors import Conflict, NotFound
from app.core.time import utcnow
from app.modules.governance.schemas import MatchingRules
from app.modules.governance.service import active_matching
from app.modules.roster.candidates import card, project_needs, visible_project
from app.modules.roster.enums import DECIDED_OUTCOMES, DETAIL_OUTCOMES, FirstShotOutcome
from app.modules.roster.models import FirstShotReview, RosterProfile
from app.modules.roster.repository import FirstShotRepository, RosterRepository
from app.modules.roster.schemas import FirstShotItem, FirstShotPanel, FirstShotReviewCreate
from app.modules.roster.scoring import ProjectNeeds, availability_fit, rank


def select_panel(
    profiles: Iterable[RosterProfile],
    *,
    project_id: UUID,
    needs: ProjectNeeds,
    rules: MatchingRules,
    exclude: set[UUID],
) -> list[RosterProfile]:
    """First-shot pool and ranking (spec §7.4). Never filtered by tier."""
    required = needs.required_skill_ids
    eligible = [
        p
        for p in profiles
        if p.worker_id not in exclude
        and required <= set(p.skill_ids)
        and availability_fit(
            p.availability_status, p.available_from, needs.starts_on, rules.availability_near_days
        )
        > 0
        and p.engagements_last_12m <= rules.first_shot.underused_max_engagements_12m
    ]

    def coverage(p: RosterProfile) -> float:
        return len(required & set(p.verified_skill_ids)) / len(required) if required else 0.0

    def rotation(p: RosterProfile) -> str:
        return hashlib.sha256(f"{project_id}:{p.worker_id}".encode()).hexdigest()

    eligible.sort(key=lambda p: (-coverage(p), p.engagements_last_12m, rotation(p)))
    return eligible[: rules.first_shot.panel_size]


async def first_shot_panel(session: AsyncSession, actor: Actor, project_id: UUID) -> FirstShotPanel:
    project = await visible_project(session, actor, project_id)
    policy = await active_matching(session)
    needs = project_needs(project, utcnow().date())
    profiles = await RosterRepository(session).eligible(project.data_region)
    reviews = FirstShotRepository(session)
    decided = {
        worker_id
        for worker_id, review in (await reviews.for_project(project.id)).items()
        if review.outcome in DECIDED_OUTCOMES
    }
    top = {
        p.worker_id
        for _, p in rank(profiles, needs, policy)[: policy.rules.first_shot.exclude_top_candidates]
    }
    panel = select_panel(
        profiles, project_id=project.id, needs=needs, rules=policy.rules, exclude=top | decided
    )
    await reviews.record_shown(project.id, [p.worker_id for p in panel], actor.user_id)
    # Another PM may have reviewed a panel worker between the two reads above;
    # populate_existing refreshes any identity-mapped rows so we return the
    # committed outcome, not a stale one held in this session's identity map.
    current = await reviews.for_project(project.id, populate_existing=True)
    return FirstShotPanel(
        project_id=project.id,
        policy_version=policy.version,
        items=[
            FirstShotItem(
                worker=card(p),
                outcome=current[p.worker_id].outcome,
                reason_code=current[p.worker_id].reason_code,
            )
            for p in panel
        ],
    )


async def review(
    session: AsyncSession,
    actor: Actor,
    project_id: UUID,
    worker_id: UUID,
    data: FirstShotReviewCreate,
) -> FirstShotReview:
    project = await visible_project(session, actor, project_id)
    row = await FirstShotRepository(session).get_for_update(project.id, worker_id)
    if row is None:
        raise NotFound(
            "This worker has not been shown on this project's first-shot panel",
            code="not_in_first_shot",
        )
    outcome = FirstShotOutcome(data.outcome)
    if outcome in DETAIL_OUTCOMES:
        eligible_ids = {
            p.worker_id for p in await RosterRepository(session).eligible(project.data_region)
        }
        if worker_id not in eligible_ids:
            raise Conflict(
                "This worker is no longer eligible for this project's data region",
                code="worker_not_eligible",
            )
    before_outcome = row.outcome
    row.outcome = outcome
    row.reason_code = data.reason_code
    row.pm_id = actor.user_id
    await session.flush()
    await write_audit(
        session,
        actor=actor,
        action="first_shot.reviewed",
        target_type="worker",
        target_id=worker_id,
        before={"outcome": before_outcome.value},
        after={
            "project_id": str(project.id),
            "outcome": row.outcome.value,
            "reason_code": row.reason_code.value if row.reason_code else None,
        },
    )
    return row

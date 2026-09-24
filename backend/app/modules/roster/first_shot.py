import hashlib
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.time import utcnow
from app.modules.governance.schemas import MatchingRules
from app.modules.governance.service import active_matching
from app.modules.roster.candidates import card, project_needs, visible_project
from app.modules.roster.enums import DECIDED_OUTCOMES
from app.modules.roster.models import RosterProfile
from app.modules.roster.repository import FirstShotRepository, RosterRepository
from app.modules.roster.schemas import FirstShotItem, FirstShotPanel
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
    current = await reviews.for_project(project.id)
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

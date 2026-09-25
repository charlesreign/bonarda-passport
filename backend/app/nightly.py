"""Nightly governance jobs (spec §7.7): concentration rollup and retention
enforcement. They gather data from several modules, so they live in the
composition root; each module still owns its own writes."""

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.engagements.service import (
    concentration_counts,
    project_regions,
    scrub_feedback_text,
)
from app.modules.governance.service import (
    ScopeCounts,
    active_concentration,
    active_retention,
    record_concentration,
    scrub_dispute_text,
)
from app.modules.passport.service import anonymize_worker, retention_due, tier_distribution
from app.modules.roster.service import first_shot_outcomes

log = structlog.get_logger(__name__)


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


async def run_concentration_rollup(session: AsyncSession) -> int:
    """Records today's rollup per scope; returns how many scopes."""
    policy = await active_concentration(session)
    today = utcnow().date()
    since = today - timedelta(days=policy.rules.window_days)
    engagements = await concentration_counts(
        session, since, today, policy.rules.repeat_min_engagements
    )
    outcomes = await first_shot_outcomes(session, datetime.combine(since, time.min, UTC))
    regions = await project_regions(session, {project_id for project_id, _ in outcomes})
    shown: Counter[str] = Counter()
    engaged: Counter[str] = Counter()
    for project_id, outcome in outcomes:
        for scope in ("ORG", regions.get(project_id)):
            if scope is None:
                continue
            shown[scope] += 1
            if outcome == "engaged":
                engaged[scope] += 1
    tiers = await tier_distribution(session)
    scopes = {"ORG"} | set(engagements) | set(shown) | set(tiers)
    counts = [
        ScopeCounts(
            scope=scope,
            engagements_total=engagements.get(scope, (0, 0))[0],
            engagements_repeat=engagements.get(scope, (0, 0))[1],
            first_shot_shown=shown[scope],
            first_shot_engaged=engaged[scope],
            tier_counts=tiers.get(scope, {}),
        )
        for scope in sorted(scopes)
    ]
    rows = await record_concentration(session, period_start=since, period_end=today, counts=counts)
    return len(rows)


async def run_retention(session: AsyncSession) -> dict[str, int]:
    """Spec §6.6. Audit-log deletion is not done here: the append-only trigger
    only lets the `bonarda_retention` database role delete, and that role is
    provisioned at deploy time (roadmap)."""
    policy = await active_retention(session)
    now = utcnow()
    today = now.date()
    rules = policy.rules
    anonymized = 0
    for worker_id in await retention_due(
        session, _years_before(today, rules.dormant_profile_years)
    ):
        if await anonymize_worker(session, worker_id, actor=None, reason="retention"):
            anonymized += 1
    feedback_cutoff = datetime.combine(
        _years_before(today, rules.feedback_text_years), time.min, UTC
    )
    dispute_cutoff = datetime.combine(_years_before(today, rules.dispute_text_years), time.min, UTC)
    result = {
        "workers_anonymized": anonymized,
        "feedback_text_removed": await scrub_feedback_text(
            session, completed_before=feedback_cutoff
        ),
        "dispute_text_removed": await scrub_dispute_text(session, resolved_before=dispute_cutoff),
    }
    log.info("retention.enforced", policy_version=policy.version, **result)
    return result

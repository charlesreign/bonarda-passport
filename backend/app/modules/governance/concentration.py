"""Concentration monitoring (spec §2.2 #4, NFR-5.3, FR-7.1/7.2). The numbers
come from other modules; the nightly job (app/nightly.py) gathers them, and
governance records them, compares them with the active policy and alerts."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.modules.governance.models import ConcentrationRollup
from app.modules.governance.policies import active_concentration
from app.modules.governance.repository import ConcentrationRepository, DisputeRepository
from app.modules.governance.schemas import (
    ConcentrationAlert,
    ConcentrationRollupRead,
    DisputeVolume,
    GovernanceOverview,
)


@dataclass(frozen=True, slots=True)
class ScopeCounts:
    scope: str  # "ORG" or a data region
    engagements_total: int = 0
    engagements_repeat: int = 0
    first_shot_shown: int = 0
    first_shot_engaged: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)


async def record_concentration(
    session: AsyncSession, *, period_start: date, period_end: date, counts: list[ScopeCounts]
) -> list[ConcentrationRollup]:
    """Upserts one row per scope and alerts once per day per scope when the
    repeat share passes the policy threshold."""
    policy = await active_concentration(session)
    repo = ConcentrationRepository(session)
    rows = []
    for c in counts:
        share = round(c.engagements_repeat / c.engagements_total, 4) if c.engagements_total else 0.0
        row = await repo.get_for_update(period_end, c.scope)
        if row is None:
            row = repo.add(ConcentrationRollup(period_end=period_end, scope=c.scope, alerted=False))
        row.period_start = period_start
        row.engagements_total = c.engagements_total
        row.engagements_repeat = c.engagements_repeat
        row.share = share
        row.first_shot_shown = c.first_shot_shown
        row.first_shot_engaged = c.first_shot_engaged
        row.tier_counts = dict(c.tier_counts)
        row.policy_version_id = policy.id
        await session.flush()
        if share > policy.rules.alert_share and not row.alerted:
            row.alerted = True
            await write_audit(
                session,
                actor=None,
                action="concentration.alert",
                target_type="concentration_rollup",
                target_id=row.id,
                after={"scope": c.scope, "share": share, "alert_share": policy.rules.alert_share},
            )
            await emit_event(
                session,
                ConcentrationAlert(
                    aggregate_id=row.id,
                    scope=c.scope,
                    share=share,
                    alert_share=policy.rules.alert_share,
                ),
            )
        rows.append(row)
    return rows


async def governance_overview(session: AsyncSession, now: datetime) -> GovernanceOverview:
    policy = await active_concentration(session)
    latest = await ConcentrationRepository(session).latest()
    disputes = await DisputeRepository(session).counts(now, now - timedelta(days=30))
    return GovernanceOverview(
        alert_share=policy.rules.alert_share,
        repeat_min_engagements=policy.rules.repeat_min_engagements,
        window_days=policy.rules.window_days,
        policy_version=policy.version,
        concentration=[ConcentrationRollupRead.model_validate(r) for r in latest],
        disputes=DisputeVolume(**disputes),
    )


async def concentration_history(
    session: AsyncSession, scope: str, limit: int
) -> list[ConcentrationRollupRead]:
    rows = await ConcentrationRepository(session).history(scope, limit)
    return [ConcentrationRollupRead.model_validate(r) for r in rows]

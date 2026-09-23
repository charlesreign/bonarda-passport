from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.outbox.models import OutboxEvent
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.stuck import flag_stuck, retry_payroll_signals
from app.modules.integrations.service import FakePayrollAdapter
from tests.support import make_engagement, make_project, make_ready_worker, make_user


async def _run(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    async with sessionmaker() as s, s.begin():
        return await flag_stuck(s, settings)


async def test_old_unsent_and_long_unsigned_contracts_are_flagged_once(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker, _ = await make_ready_worker(session)
    now = utcnow()
    unsent = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="A")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
    )
    unsigned = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="B")).id,
        status=EngagementStatus.AWAITING_SIGNATURE,
    )
    fresh = await make_engagement(
        session,
        worker_id=worker.id,
        project_id=(await make_project(session, staff=[pm], name="C")).id,
        status=EngagementStatus.PENDING_SIGNATURE,
    )
    await session.execute(
        update(Engagement)
        .where(Engagement.id == unsent.id)
        .values(confirmed_at=now - timedelta(minutes=31))
    )
    await session.execute(
        update(Engagement)
        .where(Engagement.id == unsigned.id)
        .values(contract_sent_at=now - timedelta(hours=73))
    )
    await session.commit()

    first = await _run(sessionmaker, settings)
    second = await _run(sessionmaker, settings)

    assert (first, second) == (2, 0)
    for engagement in (unsent, unsigned, fresh):
        await session.refresh(engagement)
    assert unsent.stuck_flagged_at is not None
    assert unsigned.stuck_flagged_at is not None
    assert fresh.stuck_flagged_at is None
    flagged = (
        await session.scalars(select(AuditLog).where(AuditLog.action == "engagement.flagged_stuck"))
    ).all()
    assert {row.target_id for row in flagged} == {unsent.id, unsigned.id}


async def test_activated_engagements_never_signalled_to_payroll_are_retried(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    drain: Callable[[], Awaitable[None]],
    payroll: FakePayrollAdapter,
) -> None:
    worker, _ = await make_ready_worker(session)
    now = utcnow()
    engagements = {}
    for name, status, billable_ago, signaled in (
        ("lost", EngagementStatus.COMPLETED, timedelta(minutes=31), False),
        ("signalled", EngagementStatus.ACTIVE, timedelta(hours=2), True),
        ("recent", EngagementStatus.ACTIVE, timedelta(minutes=5), False),
    ):
        engagement = await make_engagement(
            session,
            worker_id=worker.id,
            project_id=(await make_project(session, name=name)).id,
            status=status,
        )
        engagement.billable_start_at = now - billable_ago
        engagement.payroll_signaled_at = now if signaled else None
        engagements[name] = engagement
    await session.commit()
    lost = engagements["lost"]

    async with sessionmaker() as s, s.begin():
        retried = await retry_payroll_signals(s, settings)

    assert retried == 1
    emitted = (
        await session.scalars(
            select(OutboxEvent.aggregate_id).where(
                OutboxEvent.event_type == "engagements.engagement_activated"
            )
        )
    ).all()
    assert emitted == [lost.id]
    audit = (
        await session.scalars(
            select(AuditLog).where(AuditLog.action == "engagement.payroll_signal_retried")
        )
    ).one()
    assert audit.target_id == lost.id

    await drain()

    await session.refresh(lost)
    assert lost.payroll_signaled_at is not None
    assert list(payroll.activations) == [lost.id]
    async with sessionmaker() as s, s.begin():
        assert await retry_payroll_signals(s, settings) == 0

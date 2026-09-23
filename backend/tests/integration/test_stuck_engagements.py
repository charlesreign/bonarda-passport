from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.models import AuditLog
from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementStatus
from app.modules.engagements.models import Engagement
from app.modules.engagements.stuck import flag_stuck
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

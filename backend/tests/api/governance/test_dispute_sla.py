from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import AccountStatus, UserRole
from app.core.time import utcnow
from app.modules.governance.service import remind_due_disputes
from app.worker import jobs
from tests.support import RecordingMailer, make_dispute, make_user, make_worker


async def test_people_ops_get_one_digest_of_overdue_and_due_soon_disputes(
    session: AsyncSession,
) -> None:
    now = utcnow()
    worker, _ = await make_worker(session)
    overdue = await make_dispute(session, worker_id=worker.id, due_at=now - timedelta(days=1))
    soon = await make_dispute(session, worker_id=worker.id, due_at=now + timedelta(days=2))
    later = await make_dispute(session, worker_id=worker.id, due_at=now + timedelta(days=20))
    closed = await make_dispute(
        session, worker_id=worker.id, due_at=now - timedelta(days=5), resolved=True
    )
    await make_user(session, role=UserRole.PEOPLE_OPS, email="ops@bonarda.works")
    await make_user(
        session,
        role=UserRole.PEOPLE_OPS,
        email="gone@bonarda.works",
        status=AccountStatus.REVOKED,
    )
    await make_user(session, role=UserRole.PM, email="pm@bonarda.works")
    mailer = RecordingMailer()

    listed = await remind_due_disputes(session, mailer, now=now, warn_days=3)

    assert listed == 2
    (mail,) = mailer.sent
    assert mail["to"] == "ops@bonarda.works"
    assert mail["subject"] == "Disputes: 1 overdue, 1 due soon"
    body = mail["body"]
    assert body.index(str(overdue.id)) < body.index(str(soon.id))
    assert str(later.id) not in body
    assert str(closed.id) not in body


async def test_no_digest_when_nothing_is_due(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    await make_dispute(session, worker_id=worker.id, due_at=utcnow() + timedelta(days=20))
    await make_user(session, role=UserRole.PEOPLE_OPS)
    mailer = RecordingMailer()

    assert await remind_due_disputes(session, mailer, now=utcnow(), warn_days=3) == 0
    assert mailer.sent == []


async def test_the_daily_job_uses_the_worker_mailer_and_settings(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    worker, _ = await make_worker(session)
    await make_dispute(session, worker_id=worker.id, due_at=utcnow() + timedelta(days=4))
    await make_user(session, role=UserRole.PEOPLE_OPS)
    mailer = RecordingMailer()
    ctx = {
        "sessionmaker": sessionmaker,
        "mailer": mailer,
        "settings": settings.model_copy(update={"dispute_reminder_days": 5}),
    }

    assert await jobs.remind_dispute_sla(ctx) == 1
    assert len(mailer.sent) == 1

from typing import ClassVar
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.audit.writer import write_audit
from app.core.context import Actor, correlation_scope
from app.core.enums import UserRole
from app.core.outbox.events import DomainEvent
from app.core.outbox.models import OutboxEvent
from app.core.outbox.writer import emit_event


class SomethingHappened(DomainEvent):
    event_type: ClassVar[str] = "test.something_happened"
    detail: str


async def test_write_audit_persists_actor_target_and_correlation(session: AsyncSession) -> None:
    actor = Actor(user_id=uuid4(), role=UserRole.PEOPLE_OPS)
    target_id = uuid4()

    with correlation_scope("corr-123"):
        await write_audit(
            session,
            actor=actor,
            action="access_grant.created",
            target_type="access_grant",
            target_id=target_id,
            after={"reason": "cross-team cover"},
            reason="cross-team cover",
        )
    await session.commit()

    row = (await session.scalars(select(AuditLog))).one()
    assert row.actor_id == actor.user_id
    assert row.actor_role == "people_ops"
    assert row.action == "access_grant.created"
    assert row.target_id == target_id
    assert row.after == {"reason": "cross-team cover"}
    assert row.correlation_id == "corr-123"


async def test_system_actor_is_recorded_as_system(session: AsyncSession) -> None:
    await write_audit(
        session, actor=None, action="grant.expired", target_type="access_grant", target_id=uuid4()
    )
    await session.commit()

    row = (await session.scalars(select(AuditLog))).one()
    assert row.actor_id is None
    assert row.actor_role == "system"


async def _one_audit_row(session: AsyncSession) -> None:
    await write_audit(session, actor=None, action="x", target_type="t", target_id=uuid4())
    await session.commit()


async def test_audit_log_rejects_update(session: AsyncSession) -> None:
    await _one_audit_row(session)

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(update(AuditLog).values(reason="tampered"))


async def test_audit_log_rejects_delete(session: AsyncSession) -> None:
    await _one_audit_row(session)

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(AuditLog))


async def test_emit_event_persists_type_payload_and_correlation(session: AsyncSession) -> None:
    aggregate_id = uuid4()

    with correlation_scope("corr-456"):
        await emit_event(session, SomethingHappened(aggregate_id=aggregate_id, detail="hello"))
    await session.commit()

    row = (await session.scalars(select(OutboxEvent))).one()
    assert row.event_type == "test.something_happened"
    assert row.aggregate_id == aggregate_id
    assert row.payload == {"aggregate_id": str(aggregate_id), "detail": "hello"}
    assert row.correlation_id == "corr-456"
    assert row.dispatched_at is None
    assert row.attempts == 0


async def test_audit_and_event_roll_back_together(session: AsyncSession) -> None:
    await write_audit(session, actor=None, action="x", target_type="t", target_id=uuid4())
    await emit_event(session, SomethingHappened(aggregate_id=uuid4(), detail="lost"))
    await session.rollback()

    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0

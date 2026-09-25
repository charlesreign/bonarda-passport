import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from alembic import command
from app.core.db.errors import violated_constraint
from app.core.time import utcnow
from app.modules.engagements.enums import (
    CancelCause,
    DeclineReason,
    EngagementPath,
    EngagementStatus,
    WorkMode,
)
from app.modules.engagements.models import Engagement
from tests.support import alembic_config, make_project, make_worker

CANCELLED = EngagementStatus.CANCELLED
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


async def _violation(session: AsyncSession, **fields: Any) -> str | None:
    """Inserts one engagement with `fields` and returns the name of the
    constraint it violated, or None if the row was accepted."""
    worker, _ = await make_worker(session)
    project = await make_project(session)
    session.add(
        Engagement(
            worker_id=worker.id,
            project_id=project.id,
            path=EngagementPath.FIRST_TIME,
            start_date=date(2026, 10, 1),
            rate=Decimal("450.00"),
            currency="GHS",
            work_mode=WorkMode.REMOTE,
            contract_terms={"scope": "Build the data pipeline", "access_notes": None},
            confirmed_at=utcnow(),
            **fields,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        return violated_constraint(exc)
    await session.rollback()
    return None


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"status": CANCELLED}, "ck_engagements_cancel_cause_when_cancelled"),
        (
            {"status": EngagementStatus.ACTIVE, "cancel_cause": CancelCause.WORKER_ACCOUNT_MISSING},
            "ck_engagements_cancel_cause_when_cancelled",
        ),
        (
            {"status": CANCELLED, "cancel_cause": CancelCause.ESIGN_DECLINED},
            "ck_engagements_declined_at_when_declined",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.WORKER_ACCOUNT_MISSING,
                "declined_at": NOW,
            },
            "ck_engagements_declined_at_when_declined",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.ESIGN_DECLINED,
                "declined_at": NOW,
                "decline_reason": DeclineReason.RATE,
            },
            "ck_engagements_reason_only_for_worker_decline",
        ),
        (
            {"status": CANCELLED, "cancel_cause": CancelCause.WORKER_DECLINED, "declined_at": NOW},
            "ck_engagements_worker_decline_has_reason",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.ESIGN_DECLINED,
                "declined_at": NOW,
                "decline_note": "Too far",
            },
            "ck_engagements_note_needs_reason",
        ),
        (
            {
                "status": CANCELLED,
                "cancel_cause": CancelCause.WORKER_DECLINED,
                "declined_at": NOW,
                "decline_reason": DeclineReason.DATES,
                "decline_note": "I start another contract that week",
            },
            None,
        ),
    ],
)
async def test_decline_columns_are_consistent_with_the_status(
    session: AsyncSession, fields: dict[str, Any], constraint: str | None
) -> None:
    assert await _violation(session, **fields) == constraint


def test_backfill_takes_the_cause_from_the_audit_trail(postgres: PostgresContainer) -> None:
    base_url: str = postgres.get_connection_url()
    url = base_url.rsplit("/", 1)[0] + "/decline_backfill"
    ids = {key: uuid4() for key in ("worker", "project", "esign", "missing", "unknown", "active")}
    declined_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    async def admin(sql: str) -> None:
        engine = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(sql))
        await engine.dispose()

    async def seed() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO workers (id, full_name, worker_type, data_region) "
                    "VALUES (:id, 'Ama Owusu', 'freelancer', 'GH')"
                ),
                {"id": ids["worker"]},
            )
            await conn.execute(
                text("INSERT INTO projects (id, name, data_region) VALUES (:id, 'Volta', 'GH')"),
                {"id": ids["project"]},
            )
            for key, status in (
                ("esign", "cancelled"),
                ("missing", "cancelled"),
                ("unknown", "cancelled"),
                ("active", "active"),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO engagements (id, worker_id, project_id, path, status, "
                        "start_date, rate, currency, work_mode, contract_terms, confirmed_at) "
                        "VALUES (:id, :worker, :project, 'first_time', :status, '2026-09-01', "
                        "450, 'GHS', 'remote', CAST(:terms AS jsonb), now())"
                    ),
                    {
                        "id": ids[key],
                        "worker": ids["worker"],
                        "project": ids["project"],
                        "status": status,
                        "terms": '{"scope": "Pipeline", "access_notes": null}',
                    },
                )
            await conn.execute(
                text(
                    "INSERT INTO audit_log (action, target_type, target_id, occurred_at) "
                    "VALUES ('engagement.contract_declined', 'engagement', :id, :at)"
                ),
                {"id": ids["esign"], "at": declined_at},
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_log (action, target_type, target_id, reason) "
                    "VALUES ('engagement.cancelled', 'engagement', :id, 'worker_account_missing')"
                ),
                {"id": ids["missing"]},
            )
        await engine.dispose()

    async def causes() -> dict[str, tuple[str | None, datetime | None]]:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT id, cancel_cause, declined_at FROM engagements"))
            ).all()
        await engine.dispose()
        by_id = {row.id: (row.cancel_cause, row.declined_at) for row in rows}
        return {key: by_id[ids[key]] for key in ("esign", "missing", "unknown", "active")}

    asyncio.run(admin("DROP DATABASE IF EXISTS decline_backfill"))
    asyncio.run(admin("CREATE DATABASE decline_backfill"))
    cfg = alembic_config(url)
    command.upgrade(cfg, "0015_concentration")
    asyncio.run(seed())

    command.upgrade(cfg, "head")

    assert asyncio.run(causes()) == {
        "esign": ("esign_declined", declined_at),
        "missing": ("worker_account_missing", None),
        "unknown": ("worker_account_missing", None),
        "active": (None, None),
    }
    asyncio.run(admin("DROP DATABASE decline_backfill"))

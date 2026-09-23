import asyncio

from sqlalchemy import CheckConstraint, Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.core.db.base import Base
from tests.support import alembic_config


async def test_head_creates_core_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {"audit_log", "outbox_events", "processed_events"} <= tables


async def test_models_match_migrations(db_engine: AsyncEngine) -> None:
    def diff(sync_conn: Connection) -> list[object]:
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return list(compare_metadata(ctx, Base.metadata))

    async with db_engine.connect() as conn:
        differences = await conn.run_sync(diff)
    assert differences == []


async def test_check_constraint_names_match_models(db_engine: AsyncEngine) -> None:
    # compare_metadata does not diff check constraints, so compare their names directly.
    expected = {
        (table.name, str(constraint.name))
        for table in Base.metadata.sorted_tables
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT rel.relname, con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
                "WHERE con.contype = 'c' AND ns.nspname = 'public'"
            )
        )
        actual = {(row.relname, row.conname) for row in result}
    assert actual == expected


def test_downgrade_to_base_then_upgrade_round_trips(postgres: PostgresContainer) -> None:
    base_url: str = postgres.get_connection_url()
    roundtrip_url = base_url.rsplit("/", 1)[0] + "/roundtrip"

    async def recreate_database() -> None:
        engine = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text("DROP DATABASE IF EXISTS roundtrip"))
            await conn.execute(text("CREATE DATABASE roundtrip"))
        await engine.dispose()

    asyncio.run(recreate_database())
    cfg = alembic_config(roundtrip_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

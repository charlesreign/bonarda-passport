import asyncio
from collections.abc import Callable
from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.db.session import create_engine
from app.core.logging import configure_logging
from app.core.outbox.relay import listen_dsn, run_relay
from app.wiring import build_registry
from app.worker.jobs import (
    MAX_HANDLER_TRIES,
    expire_access_grants,
    purge_outbox,
    run_event_handler,
)

log = structlog.get_logger(__name__)


def _log_if_relay_died_unexpectedly(
    stop: asyncio.Event,
) -> Callable[[asyncio.Task[None]], None]:
    def _callback(task: asyncio.Task[None]) -> None:
        if stop.is_set() or task.cancelled():
            return
        exc = task.exception()
        # Reached even when exc is None: after this fix run_relay only ever
        # returns while `stop` is set, so any other exit — with or without an
        # exception — means outbox dispatch has silently stopped forever.
        log.error("outbox.relay_stopped", exc_info=exc)

    return _callback


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(json_logs=settings.env != "dev")
    engine = create_engine(settings)
    ctx["engine"] = engine
    ctx["sessionmaker"] = async_sessionmaker(engine, expire_on_commit=False)
    ctx["registry"] = build_registry()
    ctx["relay_stop"] = asyncio.Event()
    relay_task = asyncio.create_task(
        run_relay(
            ctx["sessionmaker"],
            ctx["registry"],
            ctx["redis"].enqueue_job,
            listen_dsn=listen_dsn(settings.database_url),
            stop=ctx["relay_stop"],
        )
    )
    relay_task.add_done_callback(_log_if_relay_died_unexpectedly(ctx["relay_stop"]))
    ctx["relay_task"] = relay_task


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["relay_stop"].set()
    await ctx["relay_task"]
    await ctx["engine"].dispose()


class WorkerSettings:
    """Run with `arq app.worker.settings.WorkerSettings`."""

    functions: ClassVar[list[Any]] = [run_event_handler]
    cron_jobs: ClassVar[list[Any]] = [
        cron(purge_outbox, hour={2}, minute={30}),
        cron(expire_access_grants, minute=set(range(0, 60, 5))),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_HANDLER_TRIES
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

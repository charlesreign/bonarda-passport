import asyncio
from collections.abc import Callable
from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import models_registry as _models_registry  # noqa: F401 (map tables before first flush)
from app.core.config import get_settings
from app.core.db.session import create_engine
from app.core.logging import configure_logging
from app.core.outbox.relay import listen_dsn, run_relay
from app.modules.integrations.service import build_esign, build_mailer, build_payroll
from app.wiring import HandlerDeps, build_registry
from app.worker.jobs import (
    MAX_HANDLER_TRIES,
    activate_due_engagements,
    expire_access_grants,
    flag_stuck_engagements,
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
    # A separate client with decoded responses, matching the API's client:
    # ctx["redis"] is Arq's own byte-oriented pool.
    handler_redis = Redis.from_url(
        settings.redis_url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0
    )
    ctx["handler_redis"] = handler_redis
    ctx["registry"] = build_registry(
        HandlerDeps(
            settings=settings,
            redis=handler_redis,
            mailer=build_mailer(settings),
            esign=build_esign(settings),
            payroll=build_payroll(settings),
        )
    )
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
    await ctx["handler_redis"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    """Run with `arq app.worker.settings.WorkerSettings`."""

    functions: ClassVar[list[Any]] = [run_event_handler]
    cron_jobs: ClassVar[list[Any]] = [
        cron(purge_outbox, hour={2}, minute={30}),
        cron(expire_access_grants, minute=set(range(0, 60, 5))),
        cron(activate_due_engagements, minute={0}),
        cron(flag_stuck_engagements, minute=set(range(0, 60, 15))),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_HANDLER_TRIES
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

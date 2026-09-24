import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from arq.worker import Retry

from app.core.config import get_settings
from app.core.outbox.processing import process_event, purge_dispatched_events
from app.modules.engagements.contracts import activate_due
from app.modules.engagements.stuck import flag_stuck, retry_payroll_signals
from app.modules.identity.grants import GrantService
from app.modules.standing.service import recalculate_all_standing

MAX_HANDLER_TRIES = 5
DEAD_LETTER_KEY = "outbox:dead_letter"
log = structlog.get_logger(__name__)


async def run_event_handler(ctx: dict[str, Any], event_id: str, handler_name: str) -> bool:
    try:
        return await process_event(
            ctx["sessionmaker"], ctx["registry"], UUID(event_id), handler_name
        )
    except Exception as exc:
        job_try: int = ctx.get("job_try", 1)
        if job_try >= MAX_HANDLER_TRIES:
            await ctx["redis"].lpush(
                DEAD_LETTER_KEY,
                json.dumps({"event_id": event_id, "handler": handler_name, "error": repr(exc)}),
            )
            log.error("outbox.handler_dead_lettered", event_id=event_id, handler=handler_name)
            return False
        raise Retry(defer=2**job_try) from exc


async def purge_outbox(ctx: dict[str, Any]) -> int:
    return await purge_dispatched_events(ctx["sessionmaker"], older_than=timedelta(days=14))


async def expire_access_grants(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await GrantService(session).sweep_expired()


async def activate_due_engagements(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await activate_due(session)


async def flag_stuck_engagements(ctx: dict[str, Any]) -> int:
    """Stalled contracts and lost payroll signals; returns how many of each were acted on."""
    settings = get_settings()
    async with ctx["sessionmaker"]() as session, session.begin():
        flagged = await flag_stuck(session, settings)
        retried = await retry_payroll_signals(session, settings)
    return flagged + retried


async def recalculate_standing(ctx: dict[str, Any]) -> int:
    async with ctx["sessionmaker"]() as session, session.begin():
        return await recalculate_all_standing(session)

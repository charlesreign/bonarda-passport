import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from arq.worker import Retry

from app.core.outbox.processing import process_event, purge_dispatched_events

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

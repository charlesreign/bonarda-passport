import re
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import correlation_scope

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

log = structlog.get_logger(__name__)


def _incoming_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"x-correlation-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_ID.fullmatch(candidate) else None
    return None


class CorrelationIdMiddleware:
    """Pure ASGI middleware: accepts a safe incoming ID or generates one, binds it
    for the whole request, and returns it in the response header.

    The ID is also stashed on scope["state"]. FastAPI's generic `Exception`
    handler runs inside Starlette's ServerErrorMiddleware, which sits *outside*
    this middleware in the stack: by the time it runs, the `with
    correlation_scope(...)` block below has already unwound (exceptions
    propagate out of it) and reset the contextvar. scope["state"] survives
    that unwind, so `errors.py` can still recover the ID for the 500 body and
    header. We also log the error here, while the contextvar is still bound,
    so the log line carries it too.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = _incoming_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        with correlation_scope(correlation_id):
            try:
                await self.app(scope, receive, send_with_header)
            except Exception:
                log.exception("request.unhandled_error")
                raise

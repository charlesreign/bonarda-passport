from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_correlation_id
from app.core.middleware import CORRELATION_HEADER

PROBLEM_JSON = "application/problem+json"

log = structlog.get_logger(__name__)


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    title: str = "Internal server error"

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        self.detail = detail or self.title
        if code is not None:
            self.code = code
        super().__init__(self.detail)


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
    title = "Bad request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    title = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    title = "Forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class UnprocessableEntity(AppError):
    status_code = 422
    code = "unprocessable"
    title = "Unprocessable request"


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Too many requests"


def _resolve_correlation_id(request: Request) -> str | None:
    """The contextvar is set for the normal request path. An unhandled
    exception unwinds CorrelationIdMiddleware's `with` block before
    ServerErrorMiddleware (outside it) calls this, resetting the contextvar —
    scope["state"], mirrored onto request.state, is the fallback."""
    return get_correlation_id() or getattr(request.state, "correlation_id", None)


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:bonarda:error:{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": request.url.path,
        "correlation_id": _resolve_correlation_id(request),
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        exc = AppError()
    return problem_response(
        request, status=exc.status_code, code=exc.code, title=exc.title, detail=exc.detail
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return problem_response(
        request,
        status=422,
        code="validation_error",
        title="Request validation failed",
        detail="One or more fields are invalid",
        extra={"errors": jsonable_encoder(errors)},
    )


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = str(exc.detail) if isinstance(exc, StarletteHTTPException) else "Error"
    headers = exc.headers if isinstance(exc, StarletteHTTPException) else None
    return problem_response(
        request,
        status=status,
        code=_HTTP_CODES.get(status, "http_error"),
        title=HTTPStatus(status).phrase,
        detail=detail,
        headers=headers,
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # CorrelationIdMiddleware already logged this (with the correlation-id
    # contextvar still bound, which it no longer is by the time we run here,
    # outside that middleware) — logging again here would double the line.
    correlation_id = _resolve_correlation_id(request)
    headers = {CORRELATION_HEADER: correlation_id} if correlation_id else None
    return problem_response(
        request,
        status=500,
        code="internal_error",
        title="Internal server error",
        detail="An unexpected error occurred",
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)

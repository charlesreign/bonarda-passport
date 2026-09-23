from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from app.modules.identity.visibility import Visibility, require_visibility, unguarded_worker_routes


def test_detects_worker_routes_without_a_guard() -> None:
    app = FastAPI()

    @app.get("/workers/{worker_id}/guarded")
    async def guarded(
        level: Annotated[Visibility, Depends(require_visibility(Visibility.SUMMARY))],
    ) -> None:
        return None

    @app.get("/workers/{worker_id}/leaky")
    async def leaky(worker_id: UUID) -> None:
        return None

    @app.get("/prefill")
    async def query_param_leak(worker_id: UUID) -> None:
        return None

    assert sorted(unguarded_worker_routes(app)) == ["/prefill", "/workers/{worker_id}/leaky"]


def test_application_has_no_unguarded_worker_routes(app: FastAPI) -> None:
    assert unguarded_worker_routes(app) == []


class _Reactivation(BaseModel):
    worker_id: UUID
    project_id: UUID


class _Grant(BaseModel):
    scoped_worker_id: UUID


def test_worker_id_in_a_request_body_is_always_reported() -> None:
    app = FastAPI()

    @app.post("/reactivations")
    async def body_addressed(body: _Reactivation) -> None:
        return None

    @app.post("/grants")
    async def differently_named(body: _Grant) -> None:
        return None

    assert unguarded_worker_routes(app) == ["/reactivations"]

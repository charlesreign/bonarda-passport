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


class _Wrapper(BaseModel):
    inner: _Reactivation


class _Batch(BaseModel):
    items: list[_Reactivation]


class _Node(BaseModel):
    name: str
    children: list["_Node"] = []


def test_worker_id_is_found_through_optional_nested_list_and_self_referential_bodies() -> None:
    app = FastAPI()

    @app.post("/optional-reactivation")
    async def optional_body(body: _Reactivation | None = None) -> None:
        return None

    @app.post("/wrapped")
    async def nested_body(body: _Wrapper) -> None:
        return None

    @app.post("/batch")
    async def list_body(body: _Batch) -> None:
        return None

    @app.post("/nodes")
    async def self_referential_without_worker_id(body: _Node) -> None:
        return None

    @app.post("/grants")
    async def differently_named(body: _Grant) -> None:
        return None

    assert sorted(unguarded_worker_routes(app)) == [
        "/batch",
        "/optional-reactivation",
        "/wrapped",
    ]

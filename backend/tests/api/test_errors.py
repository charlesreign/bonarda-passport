import re

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.errors import NotFound


class _Body(BaseModel):
    name: str


@pytest.fixture
def error_routes(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/_test/missing-worker")
    async def missing_worker() -> None:
        raise NotFound("Worker not found", code="worker_not_found")

    @router.post("/_test/validate")
    async def validate(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    @router.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    app.include_router(router)


@pytest.mark.usefixtures("error_routes")
async def test_app_error_renders_problem_json(client: AsyncClient) -> None:
    response = await client.get("/_test/missing-worker")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "worker_not_found"
    assert body["type"] == "urn:bonarda:error:worker_not_found"
    assert body["detail"] == "Worker not found"
    assert body["instance"] == "/_test/missing-worker"
    assert body["correlation_id"] == response.headers["x-correlation-id"]


@pytest.mark.usefixtures("error_routes")
async def test_validation_error_renders_problem_json(client: AsyncClient) -> None:
    response = await client.post("/_test/validate", json={})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["loc"] == ["body", "name"]


async def test_unknown_route_renders_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_correlation_id_is_generated_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-correlation-id"])


async def test_valid_incoming_correlation_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Correlation-ID": "spa-req.42_a-b"})

    assert response.headers["x-correlation-id"] == "spa-req.42_a-b"


@pytest.mark.parametrize("hostile", ["a" * 65, "has space", "semi;colon", 'quote"d'])
async def test_hostile_correlation_id_is_replaced(client: AsyncClient, hostile: str) -> None:
    response = await client.get("/health", headers={"X-Correlation-ID": hostile})

    returned = response.headers["x-correlation-id"]
    assert returned != hostile
    assert re.fullmatch(r"[0-9a-f]{32}", returned)


@pytest.mark.usefixtures("error_routes")
async def test_unhandled_error_renders_problem_json_without_leaking_detail(
    app: FastAPI,
) -> None:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://api.test") as raw_client:
        response = await raw_client.get("/_test/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "internal_error"
    assert "secret internals" not in response.text

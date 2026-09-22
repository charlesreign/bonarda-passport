from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI

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

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.modules.identity.service import Permission, require_permission
from tests.support import bearer, make_user


@pytest.fixture
def guarded_route(app: FastAPI) -> None:
    router = APIRouter()

    @router.post(
        "/_test/grants", dependencies=[Depends(require_permission(Permission.ACCESS_GRANT_MANAGE))]
    )
    async def create() -> dict[str, str]:
        return {"ok": "yes"}

    app.include_router(router)


pytestmark = pytest.mark.usefixtures("guarded_route")


async def test_role_with_permission_passes(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)

    response = await client.post("/_test/grants", headers=bearer(settings, ops))

    assert response.status_code == 200


async def test_role_without_permission_is_forbidden(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    pm = await make_user(session, role=UserRole.PM)

    response = await client.post("/_test/grants", headers=bearer(settings, pm))

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"

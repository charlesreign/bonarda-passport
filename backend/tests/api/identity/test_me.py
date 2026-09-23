from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from tests.support import bearer, make_user


async def test_me_reports_locale(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)

    response = await client.get("/api/v1/me", headers=bearer(settings, user))

    assert response.json()["locale"] == "en"


async def test_user_can_change_their_locale(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.WORKER)

    response = await client.patch(
        "/api/v1/me", json={"locale": "fr"}, headers=bearer(settings, user)
    )

    assert response.status_code == 200
    assert response.json()["locale"] == "fr"
    await session.refresh(user)
    assert user.locale == "fr"


async def test_unsupported_locale_is_rejected(
    client: AsyncClient, session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, role=UserRole.PM)

    response = await client.patch(
        "/api/v1/me", json={"locale": "de"}, headers=bearer(settings, user)
    )

    assert response.status_code == 422

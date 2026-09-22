from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from app.core.config import Settings
from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.core.errors import Unauthorized
from app.modules.identity.dependencies import CurrentActor
from app.modules.identity.repository import UserRepository
from app.modules.identity.schemas import MeResponse, TokenResponse
from app.modules.identity.sessions import IssuedSession, SessionService

router = APIRouter(prefix="/api/v1", tags=["identity"])

REFRESH_COOKIE = "bonarda_refresh"
COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, settings: Settings, issued: IssuedSession) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=issued.refresh_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> TokenResponse:
    if not refresh_token:
        raise Unauthorized("Missing refresh cookie", code="missing_refresh")
    issued = await SessionService(session, settings).rotate(refresh_token)
    set_refresh_cookie(response, settings, issued)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post("/auth/logout", status_code=204)
async def logout(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> None:
    if refresh_token:
        await SessionService(session, settings).end(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.get("/me")
async def me(actor: CurrentActor, session: SessionDep) -> MeResponse:
    user = await UserRepository(session).get(actor.user_id)
    if user is None:
        raise Unauthorized("Account no longer exists", code="account_inactive")
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        worker_id=user.worker_id,
        can_view_governance=user.can_view_governance,
    )

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.context import Actor
from app.core.deps import RedisDep, SettingsDep
from app.core.errors import Unauthorized
from app.modules.identity.revocation import is_revoked
from app.modules.identity.tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_actor(
    settings: SettingsDep,
    redis: RedisDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Actor:
    if credentials is None:
        raise Unauthorized("Missing bearer token", code="missing_token")
    claims = decode_access_token(settings, credentials.credentials)
    if await is_revoked(redis, claims.user_id, claims.issued_at):
        raise Unauthorized("Session has been revoked", code="session_revoked")
    return Actor(user_id=claims.user_id, role=claims.role, worker_id=claims.worker_id)


CurrentActor = Annotated[Actor, Depends(get_current_actor)]

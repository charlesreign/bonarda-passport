import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    role: UserRole
    worker_id: UUID | None
    issued_at: datetime
    amr: list[str]


def issue_access_token(
    settings: Settings,
    *,
    user_id: UUID,
    role: UserRole,
    worker_id: UUID | None,
    amr: list[str],
    now: datetime | None = None,
) -> str:
    issued = int((now or utcnow()).timestamp())
    payload: dict[str, object] = {
        "sub": str(user_id),
        "role": role.value,
        "amr": amr,
        "iat": issued,
        "exp": issued + settings.access_token_ttl_seconds,
        "jti": uuid4().hex,
        "typ": "access",
    }
    if worker_id is not None:
        payload["wid"] = str(worker_id)
    return jwt.encode(
        payload, settings.jwt_signing_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    invalid = Unauthorized("Invalid or expired access token", code="invalid_token")
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "role"]},
        )
        if payload.get("typ") != "access":
            raise invalid
        return AccessClaims(
            user_id=UUID(payload["sub"]),
            role=UserRole(payload["role"]),
            worker_id=UUID(payload["wid"]) if payload.get("wid") else None,
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            amr=[str(a) for a in payload.get("amr", [])],
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise invalid from exc


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.errors import Unauthorized
from app.core.time import utcnow
from app.modules.identity.tokens import (
    decode_access_token,
    hash_token,
    issue_access_token,
    new_opaque_token,
)


def test_access_token_round_trips_claims(settings: Settings) -> None:
    user_id, worker_id = uuid4(), uuid4()

    token = issue_access_token(
        settings, user_id=user_id, role=UserRole.WORKER, worker_id=worker_id, amr=["email"]
    )
    claims = decode_access_token(settings, token)

    assert claims.user_id == user_id
    assert claims.role is UserRole.WORKER
    assert claims.worker_id == worker_id
    assert claims.amr == ["email"]


def test_expired_token_is_rejected(settings: Settings) -> None:
    token = issue_access_token(
        settings,
        user_id=uuid4(),
        role=UserRole.PM,
        worker_id=None,
        amr=[],
        now=utcnow() - timedelta(seconds=settings.access_token_ttl_seconds + 5),
    )

    with pytest.raises(Unauthorized) as excinfo:
        decode_access_token(settings, token)
    assert excinfo.value.code == "invalid_token"


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    other = settings.model_copy(
        update={"jwt_signing_key": SecretStr("another-key-that-is-32-bytes-long!!")}
    )
    token = issue_access_token(other, user_id=uuid4(), role=UserRole.PM, worker_id=None, amr=[])

    with pytest.raises(Unauthorized):
        decode_access_token(settings, token)


def test_token_without_access_type_is_rejected(settings: Settings) -> None:
    now = int(utcnow().timestamp())
    token = jwt.encode(
        {"sub": str(uuid4()), "role": "pm", "iat": now, "exp": now + 60, "typ": "refresh"},
        settings.jwt_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(Unauthorized):
        decode_access_token(settings, token)


def test_token_with_unknown_role_is_rejected(settings: Settings) -> None:
    now = int(utcnow().timestamp())
    token = jwt.encode(
        {"sub": str(uuid4()), "role": "superuser", "iat": now, "exp": now + 60, "typ": "access"},
        settings.jwt_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(Unauthorized):
        decode_access_token(settings, token)


def test_opaque_tokens_are_unique_and_hash_to_64_hex_chars() -> None:
    first, second = new_opaque_token(), new_opaque_token()

    assert first != second
    assert len(hash_token(first)) == 64
    assert hash_token(first) == hash_token(first)

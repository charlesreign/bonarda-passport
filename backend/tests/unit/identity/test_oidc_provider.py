"""Network-free tests for AuthlibOidcProvider's JWKS refresh-on-unknown-kid
and algorithm pinning. Metadata and JWKS are injected directly onto the
provider's private attributes — a deliberately small seam that lets us drive
_decode_id_token without any HTTP calls (see app/modules/identity/oidc.py)."""

import json
import time
from typing import Any

import pytest
from authlib.jose import JsonWebKey
from authlib.jose import jwt as unpinned_jwt
from authlib.jose.errors import UnsupportedAlgorithmError

from app.core.config import Settings
from app.modules.identity.oidc import AuthlibOidcProvider

ISSUER = "https://idp.test/realms/bonarda"


def _public_jwk(key: Any) -> dict[str, Any]:
    return dict(json.loads(key.as_json(is_private=False)))


def _sign(key: Any, *, kid: str, alg: str, nonce: str, aud: str) -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": aud,
        "sub": "user-1",
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
    }
    token: str | bytes = unpinned_jwt.encode({"alg": alg, "kid": kid}, payload, key)
    return token.decode() if isinstance(token, bytes) else token


def _provider(settings: Settings) -> AuthlibOidcProvider:
    provider = AuthlibOidcProvider(settings)
    provider._metadata = {"issuer": ISSUER, "jwks_uri": "https://idp.test/jwks"}
    return provider


async def test_decode_refreshes_jwks_once_when_kid_is_unknown_then_succeeds(
    settings: Settings,
) -> None:
    """Simulates IdP key rotation: the provider only holds the old key (A)
    when the ID token arrives signed with the new one (B). The decode must
    refresh JWKS exactly once and succeed on the retry."""
    provider = _provider(settings)
    key_a = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "kid-a"})
    key_b = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "kid-b"})
    provider._jwks = JsonWebKey.import_key_set({"keys": [_public_jwk(key_a)]})

    refresh_calls = 0

    async def fake_fetch_jwks() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        provider._jwks = JsonWebKey.import_key_set({"keys": [_public_jwk(key_b)]})
        provider._jwks_fetched_at = time.monotonic()

    provider._fetch_jwks = fake_fetch_jwks  # type: ignore[method-assign]

    token = _sign(key_b, kid="kid-b", alg="RS256", nonce="nonce-1", aud=settings.oidc_client_id)

    claims = await provider._decode_id_token(token, "nonce-1")

    assert claims.subject == "user-1"
    assert refresh_calls == 1


async def test_decode_rejects_a_token_using_a_disallowed_algorithm(settings: Settings) -> None:
    """HS256 is not in ALLOWED_ID_TOKEN_ALGORITHMS — pinning must reject it
    outright rather than trying to verify it against the (RSA) key set."""
    provider = _provider(settings)
    key_a = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "kid-a"})
    provider._jwks = JsonWebKey.import_key_set({"keys": [_public_jwk(key_a)]})
    provider._jwks_fetched_at = time.monotonic()

    token = _sign(
        "some-shared-secret",
        kid="kid-a",
        alg="HS256",
        nonce="nonce-1",
        aud=settings.oidc_client_id,
    )

    with pytest.raises(UnsupportedAlgorithmError):
        await provider._decode_id_token(token, "nonce-1")

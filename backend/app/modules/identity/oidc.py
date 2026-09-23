import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, JsonWebToken

from app.core.config import Settings

# Algorithms accepted for staff ID tokens. Pinned explicitly (rather than
# trusting whatever `alg` the token header claims) so a token signed with a
# weak or unexpected algorithm — e.g. HS256, which would let anyone who knows
# a *public* key material forge a token if the verifier just used it as an
# HMAC secret — is rejected outright.
ALLOWED_ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]

# Rate limit on refetching JWKS after a decode fails with an unknown key id:
# bounds how often a malicious or misbehaving `kid` can make us hit the IdP.
JWKS_MIN_REFRESH_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class IdTokenClaims:
    subject: str
    email: str
    amr: list[str]
    acr: str | None
    groups: list[str]


class OidcProvider(Protocol):
    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str: ...

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> IdTokenClaims: ...


class AuthlibOidcProvider:
    """Authorization-code flow with PKCE against the corporate IdP. Discovery
    metadata is fetched once and cached for the process lifetime. JWKS is
    fetched separately (so it can be refreshed on its own after IdP key
    rotation) and re-fetched, rate-limited, whenever a decode fails because of
    an unrecognized key id — otherwise every staff login would 500 from the
    moment the IdP rotates its signing key until this process restarts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._metadata: dict[str, Any] | None = None
        self._jwks: Any = None
        self._jwks_fetched_at: float = 0.0
        self._jwt = JsonWebToken(ALLOWED_ID_TOKEN_ALGORITHMS)

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is None:
            issuer = self._settings.oidc_issuer_url.rstrip("/")
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as http:
                meta = await http.get(f"{issuer}/.well-known/openid-configuration")
                meta.raise_for_status()
                self._metadata = meta.json()
            await self._fetch_jwks()
        return self._metadata

    async def _fetch_jwks(self) -> None:
        assert self._metadata is not None
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as http:
            keys = await http.get(self._metadata["jwks_uri"])
            keys.raise_for_status()
        self._jwks = JsonWebKey.import_key_set(keys.json())
        self._jwks_fetched_at = time.monotonic()

    async def _maybe_refresh_jwks(self) -> bool:
        """Refreshes JWKS and returns True, unless we already refreshed within
        JWKS_MIN_REFRESH_INTERVAL_SECONDS (in which case it returns False
        without hitting the network again)."""
        if time.monotonic() - self._jwks_fetched_at < JWKS_MIN_REFRESH_INTERVAL_SECONDS:
            return False
        await self._fetch_jwks()
        return True

    def _client(self) -> AsyncOAuth2Client:
        s = self._settings
        return AsyncOAuth2Client(
            client_id=s.oidc_client_id,
            client_secret=s.oidc_client_secret.get_secret_value(),
            redirect_uri=s.oidc_redirect_url,
            scope="openid email profile",
            code_challenge_method="S256",
            timeout=10.0,
        )

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        metadata = await self._discover()
        async with self._client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=code_verifier,
                max_age=str(self._settings.oidc_max_age_seconds),  # NFR-3.6: ≤ 30 days
            )
        return str(url)

    async def _decode_id_token(self, id_token: str, nonce: str) -> IdTokenClaims:
        assert self._metadata is not None
        claims_options = {
            "iss": {"essential": True, "value": self._metadata["issuer"]},
            "aud": {"essential": True, "value": self._settings.oidc_client_id},
            "nonce": {"essential": True, "value": nonce},
        }
        try:
            claims = self._jwt.decode(id_token, self._jwks, claims_options=claims_options)
        except ValueError:
            # authlib raises a plain ValueError ("Invalid JSON Web Key Set")
            # when the token's `kid` isn't in the key set we hold — the
            # expected shape of "the IdP rotated its signing key". Anything
            # else (bad signature, disallowed alg, malformed token) raises a
            # different, more specific authlib.jose error and is not retried.
            if not await self._maybe_refresh_jwks():
                raise
            claims = self._jwt.decode(id_token, self._jwks, claims_options=claims_options)
        claims.validate(leeway=30)
        return IdTokenClaims(
            subject=str(claims["sub"]),
            email=str(claims.get("email", "")),
            amr=[str(a) for a in claims.get("amr") or []],
            acr=str(claims["acr"]) if claims.get("acr") else None,
            # Keycloak sends full group paths ("/bonarda-pm").
            groups=[str(g).lstrip("/") for g in claims.get("groups") or []],
        )

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> IdTokenClaims:
        metadata = await self._discover()
        async with self._client() as client:
            token = await client.fetch_token(
                metadata["token_endpoint"], code=code, code_verifier=code_verifier
            )
        return await self._decode_id_token(token["id_token"], nonce)

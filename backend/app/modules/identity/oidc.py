from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, jwt

from app.core.config import Settings


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
    """Authorization-code flow with PKCE against the corporate IdP. Discovery and
    JWKS are fetched lazily on first use and cached for the process lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._metadata: dict[str, Any] | None = None
        self._jwks: Any = None

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is None:
            issuer = self._settings.oidc_issuer_url.rstrip("/")
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as http:
                meta = await http.get(f"{issuer}/.well-known/openid-configuration")
                meta.raise_for_status()
                metadata: dict[str, Any] = meta.json()
                keys = await http.get(metadata["jwks_uri"])
                keys.raise_for_status()
            self._jwks = JsonWebKey.import_key_set(keys.json())
            self._metadata = metadata
        return self._metadata

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

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> IdTokenClaims:
        metadata = await self._discover()
        async with self._client() as client:
            token = await client.fetch_token(
                metadata["token_endpoint"], code=code, code_verifier=code_verifier
            )
        claims = jwt.decode(
            token["id_token"],
            self._jwks,
            claims_options={
                "iss": {"essential": True, "value": metadata["issuer"]},
                "aud": {"essential": True, "value": self._settings.oidc_client_id},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate(leeway=30)
        return IdTokenClaims(
            subject=str(claims["sub"]),
            email=str(claims.get("email", "")),
            amr=[str(a) for a in claims.get("amr") or []],
            acr=str(claims["acr"]) if claims.get("acr") else None,
            # Keycloak sends full group paths ("/bonarda-pm").
            groups=[str(g).lstrip("/") for g in claims.get("groups") or []],
        )

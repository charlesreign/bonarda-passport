from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import UserRole

NON_PRODUCTION_ENVS: frozenset[str] = frozenset({"dev", "test"})
_MIN_SECRET_LENGTH = 32
_PLACEHOLDER = "change-me"


def _check_strong_secret(value: SecretStr, *, field: str) -> None:
    raw = value.get_secret_value()
    if _PLACEHOLDER in raw.lower():
        raise ValueError(f"{field} must not contain a placeholder value ('{_PLACEHOLDER}')")
    if len(raw) < _MIN_SECRET_LENGTH:
        raise ValueError(f"{field} must be at least {_MIN_SECRET_LENGTH} characters")


def _check_no_placeholder(value: SecretStr, *, field: str) -> None:
    if _PLACEHOLDER in value.get_secret_value().lower():
        raise ValueError(f"{field} must not contain a placeholder value ('{_PLACEHOLDER}')")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str
    db_pool_size: int = 10
    redis_url: str
    public_app_url: str

    jwt_signing_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 600
    staff_idle_timeout_seconds: int = 1_800
    staff_session_max_seconds: int = 43_200
    worker_idle_timeout_seconds: int = 86_400
    worker_session_max_seconds: int = 2_592_000
    revocation_marker_ttl_seconds: int = 900
    cookie_secure: bool = True

    magic_link_ttl_seconds: int = 900
    magic_link_per_email_per_hour: int = 5
    magic_link_per_ip_per_hour: int = 20

    oidc_issuer_url: str
    oidc_client_id: str
    oidc_client_secret: SecretStr
    oidc_redirect_url: str
    oidc_required_amr: list[str] = Field(default_factory=lambda: ["mfa", "otp", "hwk", "swk"])
    oidc_accepted_acr: list[str] = Field(default_factory=list)
    oidc_group_role_map: dict[str, UserRole] = Field(default_factory=dict)
    oidc_max_age_seconds: int = 2_592_000

    scim_bearer_token: SecretStr

    # smtp://user:pass@host:port (STARTTLS when offered) or smtps://… (implicit TLS).
    # Unset in dev/test means mail is written to the log instead.
    smtp_url: SecretStr | None = None
    mail_from: str = "Bonarda Works <no-reply@bonarda.works>"

    @model_validator(mode="after")
    def _require_production_hardening(self) -> Self:
        """Outside dev/test, refuse to start with a weak or placeholder secret,
        or with cookies allowed over plain HTTP — cheap to check once here
        instead of relying on every environment being configured correctly."""
        if self.env in NON_PRODUCTION_ENVS:
            return self
        _check_strong_secret(self.jwt_signing_key, field="jwt_signing_key")
        _check_strong_secret(self.scim_bearer_token, field="scim_bearer_token")
        _check_no_placeholder(self.oidc_client_secret, field="oidc_client_secret")
        if not self.cookie_secure:
            raise ValueError("cookie_secure must be true outside dev/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

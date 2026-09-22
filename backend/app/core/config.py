from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import UserRole


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


@lru_cache
def get_settings() -> Settings:
    return Settings()

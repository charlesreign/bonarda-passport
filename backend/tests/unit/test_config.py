from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.main import create_app


def _prod_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "env": "prod",
        "database_url": "postgresql+asyncpg://user:pw@db.internal/bonarda",
        "redis_url": "redis://redis.internal:6379/0",
        "public_app_url": "https://app.bonarda.works",
        "jwt_signing_key": SecretStr("a" * 32),
        "cookie_secure": True,
        "oidc_issuer_url": "https://idp.bonarda.works/realms/bonarda",
        "oidc_client_id": "bonarda-api",
        "oidc_client_secret": SecretStr("a-real-oidc-client-secret"),
        "oidc_redirect_url": "https://app.bonarda.works/api/v1/auth/oidc/callback",
        "scim_bearer_token": SecretStr("b" * 32),
        "esign_webhook_secret": SecretStr("c" * 32),
    }
    kwargs.update(overrides)
    return kwargs


def test_prod_jwt_signing_key_too_short_is_rejected() -> None:
    with pytest.raises(ValidationError, match="jwt_signing_key"):
        Settings(**_prod_kwargs(jwt_signing_key=SecretStr("too-short")))


def test_prod_jwt_signing_key_placeholder_is_rejected() -> None:
    with pytest.raises(ValidationError, match="jwt_signing_key"):
        Settings(**_prod_kwargs(jwt_signing_key=SecretStr("change-me-0123456789-0123456789")))


def test_prod_scim_bearer_token_too_short_is_rejected() -> None:
    with pytest.raises(ValidationError, match="scim_bearer_token"):
        Settings(**_prod_kwargs(scim_bearer_token=SecretStr("short")))


def test_prod_scim_bearer_token_placeholder_is_rejected() -> None:
    with pytest.raises(ValidationError, match="scim_bearer_token"):
        Settings(**_prod_kwargs(scim_bearer_token=SecretStr("Change-Me-0123456789-0123456789")))


def test_prod_oidc_client_secret_placeholder_is_rejected() -> None:
    with pytest.raises(ValidationError, match="oidc_client_secret"):
        Settings(**_prod_kwargs(oidc_client_secret=SecretStr("CHANGE-ME")))


def test_prod_cookie_not_secure_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cookie_secure"):
        Settings(**_prod_kwargs(cookie_secure=False))


def test_valid_prod_settings_pass() -> None:
    settings = Settings(**_prod_kwargs())

    assert settings.env == "prod"


def test_dev_settings_skip_the_production_checks() -> None:
    settings = Settings(
        **_prod_kwargs(env="dev", jwt_signing_key=SecretStr("short"), cookie_secure=False)
    )

    assert settings.env == "dev"


def test_create_app_without_a_mailer_in_prod_refuses_to_start() -> None:
    settings = Settings(**_prod_kwargs())

    with pytest.raises(RuntimeError, match="mailer"):
        create_app(settings)


def test_prod_esign_webhook_secret_must_be_strong() -> None:
    with pytest.raises(ValidationError, match="esign_webhook_secret"):
        Settings(**_prod_kwargs(esign_webhook_secret=SecretStr("short")))

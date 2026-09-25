"""Writes the OpenAPI schema for the frontend's generated client.

Run from backend/: `python -m app.export_openapi ../frontend/openapi.json`.
Settings are placeholders: building the schema touches no database or Redis."""

import json
import sys
from pathlib import Path

from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


def main(path: str) -> None:
    settings = Settings(
        env="dev",
        demo_mode=True,
        database_url="postgresql+asyncpg://schema:schema@localhost:1/schema",
        redis_url="redis://localhost:1/0",
        public_app_url="http://localhost",
        jwt_signing_key=SecretStr("schema-export-key-0123456789abcdef"),
        oidc_issuer_url="http://localhost/oidc",
        oidc_client_id="schema",
        oidc_client_secret=SecretStr("schema"),
        oidc_redirect_url="http://localhost/callback",
        scim_bearer_token=SecretStr("schema-export-token-0123456789abcdef"),
        esign_webhook_secret=SecretStr("schema-export-secret-0123456789abcdef"),
    )
    schema = create_app(settings).openapi()
    Path(path).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])

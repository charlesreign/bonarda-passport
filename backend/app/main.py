from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import models_registry as _models_registry  # noqa: F401 (map tables before first flush)
from app.core import health
from app.core.config import NON_PRODUCTION_ENVS, Settings, get_settings
from app.core.db.session import create_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.mail import Mailer
from app.core.middleware import CorrelationIdMiddleware
from app.modules.engagements.router import router as engagements_router
from app.modules.governance.router import router as governance_router
from app.modules.identity.oidc import AuthlibOidcProvider
from app.modules.identity.router import router as identity_router
from app.modules.identity.service import VisibilityPolicy
from app.modules.integrations.service import build_mailer
from app.modules.passport.router import router as passport_router
from app.modules.passport.service import is_surfaced
from app.modules.roster.router import router as roster_router
from app.modules.standing.router import router as standing_router
from app.wiring import dispute_target_owners, visibility_sources


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.redis.aclose()
    await app.state.engine.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    redis: Redis | None = None,
    mailer: Mailer | None = None,
) -> FastAPI:
    """App factory. Run with `uvicorn app.main:create_app --factory`."""
    settings = settings or get_settings()
    mailer = mailer or build_mailer(settings)
    configure_logging(json_logs=settings.env != "dev")
    app = FastAPI(title="Bonarda Works API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine or create_engine(settings)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = redis or Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=1.0,
        socket_connect_timeout=1.0,
    )
    app.state.mailer = mailer
    app.state.oidc_provider = AuthlibOidcProvider(settings)
    app.state.visibility_policy = VisibilityPolicy(visibility_sources(), surfaced=is_surfaced)
    app.state.dispute_target_owners = dispute_target_owners()
    install_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(health.router)
    app.include_router(identity_router)
    app.include_router(passport_router)
    app.include_router(engagements_router)
    app.include_router(governance_router)
    app.include_router(standing_router)
    app.include_router(roster_router)
    if settings.demo_mode and settings.env in NON_PRODUCTION_ENVS:
        from app.demo import router as demo_router

        app.include_router(demo_router)
    return app

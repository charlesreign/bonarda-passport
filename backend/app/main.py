from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core import health
from app.core.config import Settings, get_settings
from app.core.db.session import create_engine


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
) -> FastAPI:
    """App factory. Run with `uvicorn app.main:create_app --factory`."""
    settings = settings or get_settings()
    app = FastAPI(title="Bonarda Works API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine or create_engine(settings)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)
    app.include_router(health.router)
    return app

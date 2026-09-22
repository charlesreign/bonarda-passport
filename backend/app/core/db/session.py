from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Commits once after the endpoint returns, so the
    domain write, its audit row and its outbox event succeed or fail together."""
    async with request.app.state.sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]

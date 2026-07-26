"""Async database engine, sessionmaker, declarative base, and init helper.

`Base` is re-exported from `app.models.base` so model modules import a single
canonical declarative base. Engine + sessionmaker live here.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.models.base import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Alias for background tasks that need a fresh session outside request scope.
async_session_maker = AsyncSessionLocal


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session; rolls back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables from `Base.metadata` (no Alembic yet).

    Tolerant of concurrent startup callers (uvicorn --reload spawns a reloader
    + a worker that may both race through the lifespan) and of pre-existing
    schema objects from prior runs: any "already exists" error is logged as
    info and the rest of the run continues. Tables that didn't exist still get
    created on this pass.
    TODO: Replace with Alembic when lead schema stabilizes.
    """
    from sqlalchemy.exc import ProgrammingError

    async with engine.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        except ProgrammingError as exc:
            stub = str(exc).lower()
            if "already exists" in stub or "duplicate" in stub:
                logger.info("init_db.already_present: %s", exc.orig)
            else:
                raise
        except Exception as exc:
            stub = str(exc).lower()
            if "already exists" in stub or "duplicate" in stub:
                logger.info("init_db.already_present: %s", exc)
            else:
                raise
    logger.info("init_db.create_all.done")


async def dispose_db() -> None:
    """Dispose the engine pool (shutdown hook)."""
    await engine.dispose()
    logger.info("dispose_db.done")
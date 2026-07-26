"""FastAPI app factory + lifespan.

Lifespan wires: checkpointer init → DB schema create_all (skipped in test) →
yield → checkpointer close.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.routers import health, whatsapp
from app.services import checkpointer_factory

logger = logging.getLogger(__name__)
logging.basicConfig(level=settings.app_log_level.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init checkpointer + create tables. Shutdown: close checkpointer.

    `app.state.db_ready` / `app.state.db_error` record whether schema creation
    succeeded, so `GET /health` can report 503 (naming the dependency) instead
    of a silent 200 against a database with no tables. The real workflow this
    protects: an operator drops the DB, starts the API expecting the lifespan
    to recreate the schema, then runs the seed script — if `init_db()` fails
    silently, the operator gets a 200 health check and no diagnosis.
    """
    logger.info("lifespan.startup", extra={"env": settings.app_env})

    try:
        await checkpointer_factory.init()
    except Exception as exc:
        logger.warning("checkpointer.init.failed: %s", exc, extra={"error": str(exc)})

    app.state.db_ready = True
    app.state.db_error = None

    if not settings.is_test_env:
        try:
            from app.core.db import init_db

            await init_db()
        except Exception as exc:
            logger.error("init_db.failed: %s", exc, extra={"error": str(exc)})
            app.state.db_ready = False
            app.state.db_error = str(exc)

    yield

    logger.info("lifespan.shutdown")
    try:
        await checkpointer_factory.close()
    except Exception as exc:
        logger.warning("checkpointer.close.failed", extra={"error": str(exc)})


app = FastAPI(title="vivi-api", version="0.1.0", lifespan=lifespan)

# Routers
app.include_router(health.router)
app.include_router(whatsapp.router)

# Exception handlers
register_exception_handlers(app)


@app.get("/")
async def root() -> dict:
    return {"name": "vivi-api", "version": "0.1.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
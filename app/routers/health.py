"""Health endpoint — readiness probe.

Reports 503 (naming the failed dependency) when the FastAPI lifespan could
not create the database schema, instead of a liveness-only 200 that would
pass against a demo deployment with no tables.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=None)
async def health(request: Request) -> dict | JSONResponse:
    """Readiness probe: 200 only if the app booted with a usable database."""
    db_ready = getattr(request.app.state, "db_ready", True)
    if not db_ready:
        db_error = getattr(request.app.state, "db_error", None)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "dependency": "database",
                "detail": db_error,
            },
        )
    return {"status": "ok"}
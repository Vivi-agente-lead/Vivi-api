"""Custom exceptions and FastAPI exception handlers.

Domain exceptions carry an error code + http status; handlers map them to a
uniform JSON envelope `{ "code": ..., "message": ... }`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class BaseError(Exception):
    """Base for all expected domain errors. Carries code + http status."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, status_code: int | None = None, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code


class NotFoundError(BaseError):
    status_code = 404
    error_code = "not_found"


class ValidationError(BaseError):
    status_code = 422
    error_code = "validation_error"


class ServiceUnavailableError(BaseError):
    status_code = 503
    error_code = "service_unavailable"


class ForbiddenError(BaseError):
    status_code = 403
    error_code = "forbidden"


def _envelope(exc: BaseError) -> dict[str, Any]:
    return {"code": exc.error_code, "message": exc.message}


def register_exception_handlers(app: FastAPI) -> None:
    """Wire BaseError subclasses to uniform JSON responses."""

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc))

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc))

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc))

    @app.exception_handler(ServiceUnavailableError)
    async def _service_unavailable(_: Request, exc: ServiceUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc))

    @app.exception_handler(BaseError)
    async def _base_error(_: Request, exc: BaseError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "Unexpected server error"},
        )
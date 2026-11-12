"""FIG backend entrypoint.

Run locally:
    uv run uvicorn app.main:app --reload --port 8000

Routing:
    /health, /ready   unversioned probes
    /api/v1/*         business endpoints (contract base path)
    /openapi.json     OpenAPI 3.1
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.api import api_router
from app.api import health as health_api
from app.core import db, neo4j
from app.core.config import settings
from app.core.context import request_id_var
from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7_str
from app.core.logging import configure_logging
from app.schemas.envelope import error_body

logger = logging.getLogger("fig.api")
access_logger = logging.getLogger("fig.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a UUIDv7 request_id, puts it in the contextvar and echoes it back."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid7_str()
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers[REQUEST_ID_HEADER] = request_id
        access_logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("api starting", extra={"version": __version__, "env": settings.app_env})
    try:
        yield
    finally:
        await db.dispose()
        await neo4j.close()
        logger.info("api stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Probes at root, business endpoints under the contract base path.
    app.include_router(health_api.router)
    app.include_router(api_router, prefix=settings.api_base_path)

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                exc.code,
                exc.message,
                getattr(request.state, "request_id", ""),
                exc.details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Without this, FastAPI answers 404 with {"detail": ...} and breaks the envelope."""
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.VALIDATION_ERROR,
            429: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)

        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                code,
                str(exc.detail),
                getattr(request.state, "request_id", ""),
                {"path": request.url.path},
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error_body(
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                getattr(request.state, "request_id", ""),
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(
            status_code=500,
            content=error_body(
                ErrorCode.INTERNAL_ERROR,
                "Internal server error",
                getattr(request.state, "request_id", ""),
            ),
        )

    return app


app = create_app()

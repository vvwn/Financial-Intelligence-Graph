"""FIG backend entrypoint.

Run locally:
    uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.api import api_router
from app.core import db, neo4j
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7_str
from app.core.logging import configure_logging
from app.schemas.envelope import error_body

logger = logging.getLogger("fig.api")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a UUIDv7 request_id and echoes it back in the response header."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid7_str()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "api starting",
        extra={"version": __version__, "env": settings.app_env},
    )
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

    app.include_router(api_router)
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

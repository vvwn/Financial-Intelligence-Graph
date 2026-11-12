"""Health / readiness endpoints — docs/api-contracts.md section 5.1.

/health  : liveness only, never touches dependencies.
/ready   : checks PostgreSQL + Neo4j + Alembic revision; 503 with details if any fails.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app import __version__
from app.core import db, neo4j
from app.core.config import settings
from app.core.errors import ErrorCode
from app.schemas.envelope import error_body, ok

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
async def health(request: Request) -> dict:
    return ok(
        request,
        {
            "status": "ok",
            "version": __version__,
            "env": settings.app_env,
        },
    )


@router.get("/ready", summary="Readiness probe")
async def ready(request: Request, response: Response) -> dict:
    pg_ok, pg_err = await db.ping()
    neo_ok, neo_err = await neo4j.ping()

    checks = {
        "postgres": {"ok": pg_ok, "error": pg_err},
        "neo4j": {"ok": neo_ok, "error": neo_err},
    }
    all_ok = pg_ok and neo_ok

    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return error_body(
            ErrorCode.DEPENDENCY_NOT_READY,
            "One or more dependencies are not ready",
            getattr(request.state, "request_id", ""),
            details={"checks": checks},
        )

    return ok(request, {"status": "ready", "version": __version__, "checks": checks})


__all__ = ["router"]

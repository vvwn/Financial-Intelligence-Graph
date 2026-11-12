"""Health / readiness endpoints.

/health  : liveness only, never touches dependencies. Unversioned on purpose —
           it is a probe, not a business endpoint.
/ready   : checks PostgreSQL + Neo4j + Alembic revision, concurrently, cached
           for a few seconds so a 1s-interval probe cannot exhaust the pool.
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app import __version__
from app.core import db, neo4j
from app.core.config import settings
from app.core.errors import ErrorCode
from app.schemas.envelope import error_body, ok

router = APIRouter(tags=["system"])

READY_CACHE_TTL_SECONDS = 5.0
_cache: dict[str, object] = {"at": 0.0, "checks": None}
_cache_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def _expected_migration_head() -> str | None:
    """Read the head revision from the Alembic script directory.

    Cached: the head only changes when the code is redeployed.
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(settings.alembic_ini_path)
        cfg.set_main_option("script_location", settings.migrations_path)
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 - readiness must degrade, not crash
        return None


async def _current_migration() -> tuple[bool, str | None, str | None]:
    """Returns (ok, current_revision, expected_revision)."""
    expected = _expected_migration_head()
    try:
        async with db.get_engine().connect() as conn:
            row = (
                await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).first()
        current = row[0] if row else None
    except Exception:  # noqa: BLE001
        return False, None, expected

    if expected is None:
        # Cannot read the script directory; do not claim readiness we cannot prove.
        return False, current, None
    return current == expected, current, expected


async def _collect_checks() -> dict[str, dict[str, object]]:
    pg_task = asyncio.create_task(db.ping())
    neo_task = asyncio.create_task(neo4j.ping())
    mig_task = asyncio.create_task(_current_migration())

    pg_ok, pg_err = await pg_task
    neo_ok, neo_err = await neo_task
    mig_ok, mig_current, mig_expected = await mig_task

    return {
        "postgres": {"ok": pg_ok, "error": pg_err},
        "neo4j": {"ok": neo_ok, "error": neo_err},
        "migration": {
            "ok": mig_ok,
            "current": mig_current,
            "expected": mig_expected,
            "error": None if mig_ok else "database revision does not match head",
        },
    }


async def _cached_checks() -> tuple[dict[str, dict[str, object]], bool]:
    """Serve from a short-lived cache so probes do not hammer the databases."""
    now = time.monotonic()
    cached = _cache["checks"]
    if cached is not None and now - float(_cache["at"]) < READY_CACHE_TTL_SECONDS:
        return cached, True  # type: ignore[return-value]

    async with _cache_lock:
        now = time.monotonic()
        cached = _cache["checks"]
        if cached is not None and now - float(_cache["at"]) < READY_CACHE_TTL_SECONDS:
            return cached, True  # type: ignore[return-value]

        checks = await _collect_checks()
        _cache["checks"] = checks
        _cache["at"] = time.monotonic()
        return checks, False


def _reset_cache() -> None:
    """Used by tests to bypass the TTL."""
    _cache["at"] = 0.0
    _cache["checks"] = None


@router.get("/health", summary="Liveness probe")
async def health(request: Request) -> dict:
    return ok(
        request,
        {"status": "ok", "version": __version__, "env": settings.app_env},
    )


@router.get("/ready", summary="Readiness probe")
async def ready(request: Request, response: Response) -> dict:
    checks, cached = await _cached_checks()
    all_ok = all(bool(v["ok"]) for v in checks.values())

    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return error_body(
            ErrorCode.DEPENDENCY_NOT_READY,
            "One or more dependencies are not ready",
            getattr(request.state, "request_id", ""),
            details={"checks": checks, "cached": cached},
        )

    return ok(
        request,
        {"status": "ready", "version": __version__, "checks": checks},
        extra={"cached": cached},
    )


__all__ = ["READY_CACHE_TTL_SECONDS", "router"]

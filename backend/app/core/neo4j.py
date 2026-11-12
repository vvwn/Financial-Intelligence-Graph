"""Neo4j driver access.

Neo4j is a DERIVED PROJECTION of PostgreSQL (ADR-0001). Only
app/graph/projector.py may write to it; everything else is read-only.
"""

from __future__ import annotations

import asyncio

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import settings

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=20,
        )
    return _driver


async def ping(timeout_seconds: float = 3.0) -> tuple[bool, str | None]:
    """Readiness probe: run a trivial Cypher round-trip."""
    async def _probe() -> None:
        async with get_driver().session(database=settings.neo4j_database) as session:
            result = await session.run("RETURN 1 AS ok")
            await result.single()

    try:
        await asyncio.wait_for(_probe(), timeout=timeout_seconds)
        return True, None
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        return False, f"{type(exc).__name__}: {exc}"


async def close() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
    _driver = None


__all__ = ["get_driver", "ping", "close"]

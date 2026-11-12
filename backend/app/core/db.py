"""PostgreSQL access: async engine, session factory, FastAPI dependency.

PostgreSQL is the single source of truth (ADR-0001). Nothing else may write
canonical state.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.sqlalchemy_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Commits on success, rolls back on exception."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ping(timeout_seconds: float = 2.0) -> tuple[bool, str | None]:
    """Cheap readiness probe. Returns (ok, error_message)."""
    import asyncio

    async def _probe() -> None:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_probe(), timeout=timeout_seconds)
        return True, None
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        return False, f"{type(exc).__name__}: {exc}"


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


__all__ = ["get_engine", "get_session", "get_session_factory", "ping", "dispose"]

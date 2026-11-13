"""Shared fixtures. DB tests require a live PostgreSQL.

Run: docker compose -f deploy/docker-compose.yml --env-file .env up -d postgres
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.core.config import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Tables wiped between tests. app_setting / alembic_version are preserved.
_MUTABLE_TABLES = (
    "relationship_history",
    "relationship_evidence",
    "claim_relationship",
    "claim_evidence",
    "relationship",
    "claim",
    "entity_mention",
    "analysis_run",
    "impact_path",
    "quality_issue",
    "evidence",
    "news_raw_event",
    "news_event",
    "news_raw",
    "dead_letter",
    "collect_run_source",
    "collect_run",
    "source",
    "company_profile",
    "entity_alias",
    "entity",
    "industry_taxonomy",
    "graph_projection_run",
    "idempotency_key",
)


@pytest.fixture(autouse=True)
async def _reset_singletons() -> AsyncIterator[None]:
    """Neo4j driver and SQLAlchemy engine are module-level singletons bound to one loop.

    pytest-asyncio gives each test its own loop, so a driver created in test A
    raises "Event loop is closed" in test B. Closing after every test forces a
    fresh driver per loop.
    """
    from app.core import db
    from app.core.neo4j import close

    yield
    await close()
    # Same reason for the SQLAlchemy engine: the app-level singleton would be
    # bound to a loop that no longer exists in the next test.
    await db.dispose()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A dedicated engine per test.

    The app's module-level engine must not be shared across tests: pytest-asyncio
    gives each test its own event loop, and a pooled connection bound to a closed
    loop raises "Event loop is closed". NullPool + per-test dispose avoids that.
    """
    engine = create_async_engine(settings.sqlalchemy_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def clean_db(session: AsyncSession) -> AsyncIterator[None]:
    """Truncate mutable tables before and after each DB test."""
    statement = text(f"TRUNCATE {', '.join(_MUTABLE_TABLES)} RESTART IDENTITY CASCADE")

    await session.execute(statement)
    await session.commit()
    yield
    await session.rollback()
    await session.execute(statement)
    await session.commit()

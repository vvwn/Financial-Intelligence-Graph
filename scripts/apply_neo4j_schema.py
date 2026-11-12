"""Apply Neo4j constraints and indexes from database/neo4j/*.cypher.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/apply_neo4j_schema.py

Idempotent: every statement uses IF NOT EXISTS, so re-running is safe.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.neo4j import close, get_driver  # noqa: E402

CYPHER_DIR = REPO_ROOT / "database" / "neo4j"
FILES = ["constraints.cypher", "indexes.cypher"]


def statements(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        out.append(line)
    # statements are one-per-block separated by ';'
    joined = " ".join(out)
    return [s.strip() for s in joined.split(";") if s.strip()]


async def main() -> int:
    driver = get_driver()
    applied = 0
    async with driver.session(database=settings.neo4j_database) as session:
        for filename in FILES:
            path = CYPHER_DIR / filename
            if not path.exists():
                print(f"skip (missing): {filename}")
                continue
            for stmt in statements(path):
                await session.run(stmt)
                applied += 1
                print(f"ok  {stmt[:78]}")

        result = await session.run("SHOW CONSTRAINTS YIELD name RETURN count(name) AS n")
        record = await result.single()
        constraints = record["n"] if record else 0

        result = await session.run("SHOW INDEXES YIELD name RETURN count(name) AS n")
        record = await result.single()
        indexes = record["n"] if record else 0

    await close()
    print(f"\napplied {applied} statements; constraints={constraints} indexes={indexes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

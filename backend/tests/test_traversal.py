"""Traversal tests: depth/limit guards, direction, disputed exclusion, paths."""

from __future__ import annotations

import pytest
from app.core.errors import AppError, ErrorCode
from app.graph import projector, traversal
from factories import (
    add_evidence,
    link_claim,
    link_evidence,
    make_claim,
    make_entity,
    make_evidence,
    make_relationship,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.db, pytest.mark.neo4j]

_SEQ = {"n": 0}


def _code() -> str:
    _SEQ["n"] += 1
    return f"{820000 + _SEQ['n']:06d}"


async def _chain(session: AsyncSession, length: int, status: str = "verified"):
    entities = [await make_entity(session, f"遍历链{_code()}", _code()) for _ in range(length + 1)]
    rels = []
    for i in range(length):
        rel = await make_relationship(session, entities[i], entities[i + 1], status=status)
        claim = await make_claim(session, entities[i], entities[i + 1])
        await link_claim(session, claim, rel)
        ev = await add_evidence(session, make_evidence("A"))
        await link_evidence(session, rel, ev, claim)
        rels.append(rel)
    await projector.project_all(session, mode="full")
    return entities, rels


async def test_depth_one_vs_two(session: AsyncSession, clean_db: None) -> None:
    entities, _ = await _chain(session, length=3)
    center = str(entities[0].id)

    one = await traversal.neighbors(center, depth=1)
    two = await traversal.neighbors(center, depth=2)

    assert len(one["nodes"]) == 2, "depth 1 reaches only the first hop"
    assert len(two["nodes"]) == 3
    assert one["depth_used"] == 1


async def test_depth_over_limit_is_rejected(session: AsyncSession, clean_db: None) -> None:
    entities, _ = await _chain(session, length=1)

    with pytest.raises(AppError) as exc:
        await traversal.neighbors(str(entities[0].id), depth=6)
    assert exc.value.code is ErrorCode.DEPTH_LIMIT_EXCEEDED


async def test_node_limit_reports_truncation(session: AsyncSession, clean_db: None) -> None:
    entities, _ = await _chain(session, length=3)

    view = await traversal.neighbors(str(entities[0].id), depth=3, node_limit=2)

    assert view["truncated"] is True
    assert len(view["nodes"]) <= 3  # center + 2


async def test_direction_filters_edges(session: AsyncSession, clean_db: None) -> None:
    entities, _ = await _chain(session, length=2)
    middle = str(entities[1].id)

    down = await traversal.neighbors(middle, direction="down", depth=1)
    up = await traversal.neighbors(middle, direction="up", depth=1)

    assert any(e["target"] == str(entities[2].id) for e in down["edges"])
    assert any(e["source"] == str(entities[0].id) for e in up["edges"])


async def test_path_between_endpoints(session: AsyncSession, clean_db: None) -> None:
    entities, _ = await _chain(session, length=3)

    result = await traversal.find_paths(str(entities[0].id), str(entities[3].id), max_depth=5)

    assert len(result["paths"]) >= 1
    path = result["paths"][0]
    assert path["depth"] == 3
    assert len(path["relationships"]) == 3


async def test_disputed_is_hidden_by_default(session: AsyncSession, clean_db: None) -> None:
    """A disputed edge must not read as established fact."""
    entities, rels = await _chain(session, length=1, status="disputed")
    center = str(entities[0].id)

    default_view = await traversal.neighbors(center, depth=1)
    assert default_view["edges"] == []

    explicit = await traversal.neighbors(center, depth=1, include_disputed=True)
    assert len(explicit["edges"]) == 1
    assert explicit["edges"][0]["status"] == "disputed"


async def test_subgraph_filters_by_industry(session: AsyncSession, clean_db: None) -> None:
    entities, _ = await _chain(session, length=2)

    view = await traversal.subgraph(industry_code="AI-COMPUTE-GPU")
    assert all(n["industry_code"] == "AI-COMPUTE-GPU" for n in view["nodes"])
    assert view["nodes"], "factory entities are all in AI-COMPUTE-GPU"


async def test_unknown_node_raises_not_found(session: AsyncSession, clean_db: None) -> None:
    with pytest.raises(AppError) as exc:
        await traversal.neighbors("00000000-0000-0000-0000-000000000000", depth=1)
    assert exc.value.code is ErrorCode.NOT_FOUND

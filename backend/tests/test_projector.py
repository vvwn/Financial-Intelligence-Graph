"""Graph projection tests against a live Neo4j.

Scope: the two primitives the full projector (TASK-202) is built on —
project one relationship, remove one edge. These tests are what make the claim
"Neo4j is only a projection" checkable rather than aspirational.
"""

from __future__ import annotations

import pytest
from app.graph.projector import (
    fetch_edge,
    project_relationship,
    purge_nodes,
    remove_relationship,
    should_project,
)
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

_CODE_SEQ = {"n": 0}


def _next_code() -> str:
    _CODE_SEQ["n"] += 1
    return f"{800000 + _CODE_SEQ['n']:06d}"


@pytest.fixture
async def cleanup_nodes():
    """Remove any nodes the test created, so runs do not accumulate graph state."""
    created: list[str] = []
    yield created
    if created:
        await purge_nodes(created)


async def _seed(
    session: AsyncSession,
    *,
    status: str,
    relationship_type: str = "supplies_to",
    grades: list[str] | None = None,
) -> tuple[object, list[str]]:
    supplier = await make_entity(session, f"投影股份{_next_code()}", _next_code())
    customer = await make_entity(session, f"投影客户{_next_code()}", _next_code())
    rel = await make_relationship(
        session, supplier, customer, status=status, relationship_type=relationship_type
    )
    claim = await make_claim(session, supplier, customer)
    await link_claim(session, claim, rel)
    for grade in (["A"] if grades is None else grades):
        ev = await add_evidence(session, make_evidence(grade))
        await link_evidence(session, rel, ev, claim)
    return rel, [str(supplier.id), str(customer.id)], claim


# ---------------------------------------------------------------------------
# Layer gates
# ---------------------------------------------------------------------------


def test_candidate_never_projects() -> None:
    ok, reason = should_project("supplies_to", "candidate")
    assert ok is False
    assert "not projectable" in reason


def test_pending_review_never_projects() -> None:
    ok, _ = should_project("supplies_to", "pending_review")
    assert ok is False


def test_potential_relations_never_project() -> None:
    """Owner decision 2026-11-13: AI inference stays out of the verified graph."""
    for rtype in (
        "potential_beneficiary",
        "potential_loser",
        "potential_supplier",
        "potential_customer",
    ):
        ok, reason = should_project(rtype, "verified")
        assert ok is False, rtype
        assert "candidate-layer" in reason


def test_verified_projects() -> None:
    ok, reason = should_project("supplies_to", "verified")
    assert ok is True
    assert reason == "ok"


# ---------------------------------------------------------------------------
# Projection behaviour
# ---------------------------------------------------------------------------


async def test_verified_relationship_is_projected(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    rel, uids, _claim = await _seed(session, status="verified", grades=["A"])
    cleanup_nodes.extend(uids)

    result = await project_relationship(session, rel.id, run_id="test-run")

    assert result.projected is True
    assert result.edges == 1

    edge = await fetch_edge(rel.id)
    assert edge is not None
    assert edge["type"] == "SUPPLIES_TO"
    assert edge["props"]["status"] == "verified"
    assert edge["props"]["evidence_count"] == 1
    assert edge["props"]["evidence_missing"] is False


async def test_projection_is_idempotent(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    rel, uids, _claim = await _seed(session, status="verified", grades=["A"])
    cleanup_nodes.extend(uids)

    await project_relationship(session, rel.id)
    await project_relationship(session, rel.id)

    from app.core.neo4j import get_driver

    driver = get_driver()
    async with driver.session() as neo:
        result = await neo.run(
            "MATCH ()-[r {rid: $rid}]->() RETURN count(r) AS n", rid=str(rel.id)
        )
        record = await result.single()
    assert record["n"] == 1, "MERGE must not duplicate edges"


async def test_candidate_relationship_is_not_projected(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    rel, uids, _claim = await _seed(session, status="candidate")
    cleanup_nodes.extend(uids)

    result = await project_relationship(session, rel.id)

    assert result.projected is False
    assert await fetch_edge(rel.id) is None


async def test_potential_relation_is_not_projected(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    rel, uids, _claim = await _seed(session, status="verified", relationship_type="potential_loser")
    cleanup_nodes.extend(uids)

    result = await project_relationship(session, rel.id)

    assert result.projected is False
    assert "candidate-layer" in result.reason
    assert await fetch_edge(rel.id) is None


async def test_disputed_is_projected_with_its_own_status(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    """Disputed stays visible for inspection but is labelled so it cannot be mistaken for fact."""
    rel, uids, _claim = await _seed(session, status="disputed", grades=["A"])
    cleanup_nodes.extend(uids)

    await project_relationship(session, rel.id)

    edge = await fetch_edge(rel.id)
    assert edge is not None
    assert edge["props"]["status"] == "disputed"


async def test_evidence_count_uses_independent_origins(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    """Three rows, one origin: the graph must say 1, not 3."""
    rel, uids, claim = await _seed(session, status="verified", grades=[])
    cleanup_nodes.extend(uids)
    for _ in range(3):
        ev = await add_evidence(session, make_evidence("C", origin_key="one-origin"))
        await link_evidence(session, rel, ev, claim)

    await project_relationship(session, rel.id)

    edge = await fetch_edge(rel.id)
    assert edge["props"]["evidence_count"] == 1


async def test_remove_relationship_removes_only_the_edge(
    session: AsyncSession, clean_db: None, cleanup_nodes: list[str]
) -> None:
    rel, uids, _claim = await _seed(session, status="verified", grades=["A"])
    cleanup_nodes.extend(uids)
    await project_relationship(session, rel.id)

    removed = await remove_relationship(rel.id)

    assert removed == 1
    assert await fetch_edge(rel.id) is None

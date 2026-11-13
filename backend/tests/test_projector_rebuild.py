"""Projector tests: full rebuild equivalence, incremental pruning, drift detection.

The claim under test is the core architectural one (ADR-0001): Neo4j is a
projection that can be destroyed and rebuilt with an identical result.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.neo4j import get_driver
from app.graph import projector
from app.services.relationship_service import transition
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
    return f"{810000 + _SEQ['n']:06d}"


async def _seed_chain(session: AsyncSession, length: int = 2) -> list:
    """Build a linear chain of verified relationships: n0 -> n1 -> ... -> nN."""
    entities = []
    for _ in range(length + 1):
        entities.append(await make_entity(session, f"投影链{_code()}", _code()))

    rels = []
    for i in range(length):
        rel = await make_relationship(session, entities[i], entities[i + 1], status="verified")
        claim = await make_claim(session, entities[i], entities[i + 1])
        await link_claim(session, claim, rel)
        ev = await add_evidence(session, make_evidence("A", origin_key=f"origin-{i}"))
        await link_evidence(session, rel, ev, claim)
        rels.append(rel)
    return [*entities, *rels]


async def _edge_snapshot(rids: list[str]) -> dict:
    """Properties per edge, excluding projection metadata (which changes every run)."""
    driver = get_driver()
    out: dict[str, dict] = {}
    async with driver.session() as neo:
        result = await neo.run(
            "MATCH ()-[r]->() WHERE r.rid IN $rids RETURN r.rid AS rid, properties(r) AS props",
            rids=rids,
        )
        async for record in result:
            props = dict(record["props"])
            for key in projector.PROJECTION_METADATA_KEYS:
                props.pop(key, None)
            out[record["rid"]] = props
    return out


async def test_full_rebuild_is_equivalent(session: AsyncSession, clean_db: None) -> None:
    """Destroy the graph, rebuild from PostgreSQL, compare edge properties."""
    seeded = await _seed_chain(session, length=3)
    rels = seeded[-3:]
    rids = [str(r.id) for r in rels]

    first = await projector.project_all(session, mode="full")
    assert first.edges_projected == 3
    snapshot_before = await _edge_snapshot(rids)

    second = await projector.project_all(session, mode="full")
    assert second.edges_projected == 3
    snapshot_after = await _edge_snapshot(rids)

    assert snapshot_before == snapshot_after, "rebuild must reproduce identical edge properties"
    assert set(snapshot_before) == set(rids)


async def test_projection_is_idempotent(session: AsyncSession, clean_db: None) -> None:
    seeded = await _seed_chain(session, length=2)
    rids = [str(r.id) for r in seeded[-2:]]

    await projector.project_all(session, mode="full")
    await projector.project_all(session, mode="full")

    driver = get_driver()
    async with driver.session() as neo:
        result = await neo.run("MATCH ()-[r]->() WHERE r.rid IN $rids RETURN count(r) AS n", rids=rids)
        record = await result.single()
    assert record["n"] == 2, "MERGE must not duplicate edges"


async def test_rejected_relationship_is_pruned_incrementally(
    session: AsyncSession, clean_db: None
) -> None:
    """A rejected edge must leave the graph on the next sweep.

    verified -> rejected is not a legal transition (the evidence trail would be
    erased), so the realistic path is verified -> disputed -> rejected.
    """
    from app.services.relationship_service import dispute

    seeded = await _seed_chain(session, length=1)
    rel = seeded[-1]

    await projector.project_all(session, mode="full")
    assert await projector.fetch_edge(rel.id) is not None

    counter = await add_evidence(session, make_evidence("A", origin_key="counter-origin"))
    await dispute(
        session,
        rel.id,
        actor="human:kevin",
        reason="客户否认合作",
        contradicting_evidence_ids=[counter.id],
    )
    await transition(session, rel.id, "rejected", actor="human:kevin", reason="证据被推翻")
    await session.commit()

    result = await projector.project_all(session, mode="incremental")
    assert result.edges_removed == 1
    assert await projector.fetch_edge(rel.id) is None

    row_still_there = await session.get(type(rel), rel.id)
    assert row_still_there is not None, "PostgreSQL row must survive; only the projection goes away"


async def test_reconcile_detects_drift(session: AsyncSession, clean_db: None) -> None:
    seeded = await _seed_chain(session, length=2)
    rids = [str(r.id) for r in seeded[-2:]]

    await projector.project_all(session, mode="full")
    assert (await projector.reconcile(session))["consistent"] is True

    # Delete one edge behind the projector's back.
    await projector.remove_relationship(uuid.UUID(rids[0]))

    report = await projector.reconcile(session)
    assert report["consistent"] is False
    assert rids[0] in report["missing"]


async def test_candidate_layer_never_reaches_graph(session: AsyncSession, clean_db: None) -> None:
    a = await make_entity(session, f"潜在{_code()}", _code())
    b = await make_entity(session, f"潜在{_code()}", _code())
    rel = await make_relationship(
        session, a, b, status="verified", relationship_type="potential_loser"
    )

    result = await projector.project_all(session, mode="full")

    assert result.edges_projected == 0
    assert await projector.fetch_edge(rel.id) is None


async def test_projection_run_is_recorded(session: AsyncSession, clean_db: None) -> None:
    from app.models.ops import GraphProjectionRun
    from sqlalchemy import select

    await _seed_chain(session, length=1)
    await projector.project_all(session, mode="full")
    await session.commit()

    runs = list((await session.execute(select(GraphProjectionRun))).scalars().all())
    assert len(runs) == 1
    assert runs[0].mode == "full"
    assert runs[0].status == "succeeded"
    assert runs[0].edges_upserted == 1

"""The only writer of Neo4j (ADR-0001).

Two entry points:

* `project_relationship` — project one relationship and its endpoints (event-driven
  updates, tests).
* `project_all` — full or incremental sweep, recorded in `graph_projection_run`,
  which also prunes edges that no longer qualify.

Invariants enforced here:
  - candidate-layer types (POTENTIAL_*) are refused before any Cypher runs
  - only PROJECTABLE_STATUSES reach the graph
  - `disputed` is projected with its own status, never as established fact
  - MERGE everywhere, so projecting twice is a no-op
  - `stock_code` is written on the node, otherwise the uniqueness constraint is inert
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.neo4j import get_driver
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.ops import GraphProjectionRun
from app.models.relationship import Relationship, RelationshipEvidence
from app.schemas.enums import PROJECTABLE_STATUSES
from app.validation.state_guard import assert_projectable

#: entity_type -> Neo4j sub-label. Whitelisted: labels cannot be parameterised.
ENTITY_LABELS: dict[str, str] = {
    "country": "Country",
    "policy": "Policy",
    "macro_event": "MacroEvent",
    "industry": "Industry",
    "sector": "Sector",
    "technology": "Technology",
    "product": "Product",
    "raw_material": "RawMaterial",
    "equipment": "Equipment",
    "listed_company": "ListedCompany",
    "private_company": "PrivateCompany",
    "subsidiary": "Subsidiary",
    "news_event": "NewsEvent",
    "research_report": "ResearchReport",
    "evidence_file": "EvidenceFile",
}

#: relationship_type -> Cypher type. Whitelisted for the same reason.
RELATIONSHIP_TYPE_TO_CYPHER: dict[str, str] = {
    "belongs_to_industry": "BELONGS_TO_INDUSTRY",
    "upstream_of": "UPSTREAM_OF",
    "downstream_of": "DOWNSTREAM_OF",
    "supplies_to": "SUPPLIES_TO",
    "purchases_from": "PURCHASES_FROM",
    "controls": "CONTROLS",
    "holds_stake_in": "HOLDS_STAKE_IN",
    "subsidiary_of": "SUBSIDIARY_OF",
    "customer_of": "CUSTOMER_OF",
    "competes_with": "COMPETES_WITH",
    "applies_technology": "APPLIES_TECHNOLOGY",
    "depends_on_product": "DEPENDS_ON_PRODUCT",
    "affected_by_policy": "AFFECTED_BY_POLICY",
    "affected_by_event": "AFFECTED_BY_EVENT",
    "demand_transmits_to": "DEMAND_TRANSMITS_TO",
}

#: Metadata that changes on every projection and is therefore excluded from the
#: rebuild-equality assertion (see docs/graph-schema.md).
PROJECTION_METADATA_KEYS = frozenset({"projected_at", "projection_run_id"})


@dataclass
class ProjectionResult:
    projected: bool
    reason: str
    nodes: int = 0
    edges: int = 0


@dataclass
class SweepResult:
    run_id: str
    mode: str
    nodes: int = 0
    edges_projected: int = 0
    edges_removed: int = 0
    skipped: list[str] = field(default_factory=list)


def should_project(relationship_type: str, status: str) -> tuple[bool, str]:
    """Cheap pre-check used by both the projector and the QA rules."""
    try:
        assert_projectable(relationship_type, status)
    except AppError as exc:
        return False, exc.message
    return True, "ok"


def _node_props(entity: Entity) -> dict:
    return {
        "uid": str(entity.id),
        "entity_type": entity.entity_type,
        "name": entity.canonical_name,
        "normalized_name": entity.normalized_name,
        "stock_code": entity.stock_code,
        "exchange": entity.exchange,
        "industry_code": entity.industry_code,
    }


async def _evidence_stats(
    session: AsyncSession, relationship_id: uuid.UUID
) -> tuple[int, int, str | None]:
    """(independent supporting origins, contradicting origins, strongest grade)."""
    stmt = (
        select(
            RelationshipEvidence.relation,
            func.count(func.distinct(Evidence.origin_key)),
            func.min(Evidence.evidence_grade),
        )
        .join(Evidence, Evidence.id == RelationshipEvidence.evidence_id)
        .where(RelationshipEvidence.relationship_id == relationship_id)
        .group_by(RelationshipEvidence.relation)
    )
    supporting = 0
    contradicting = 0
    best: str | None = None
    for relation, origins, grade in (await session.execute(stmt)).all():
        if relation == "supporting":
            supporting = int(origins or 0)
            best = grade
        else:
            contradicting = int(origins or 0)
    return supporting, contradicting, best


async def _build_payload(session: AsyncSession, rel: Relationship) -> dict | None:
    """Assemble everything the graph needs for one relationship, or None if ineligible."""
    ok, _ = should_project(rel.relationship_type, rel.status)
    if not ok:
        return None

    source = (
        await session.execute(select(Entity).where(Entity.id == rel.source_entity_id))
    ).scalar_one_or_none()
    target = (
        await session.execute(select(Entity).where(Entity.id == rel.target_entity_id))
    ).scalar_one_or_none()
    if source is None or target is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "Relationship endpoint is missing",
            details={"relationship_id": str(rel.id)},
        )

    for entity in (source, target):
        if entity.entity_type not in ENTITY_LABELS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"entity_type {entity.entity_type} has no Neo4j label",
                details={"entity_id": str(entity.id)},
            )

    supporting, contradicting, best_grade = await _evidence_stats(session, rel.id)

    return {
        "src_uid": str(source.id),
        "src_props": _node_props(source),
        "src_label": ENTITY_LABELS[source.entity_type],
        "tgt_uid": str(target.id),
        "tgt_props": _node_props(target),
        "tgt_label": ENTITY_LABELS[target.entity_type],
        "cypher_type": RELATIONSHIP_TYPE_TO_CYPHER[rel.relationship_type],
        "rid": str(rel.id),
        "status": rel.status,
        "confidence": float(rel.confidence),
        "valid_from": rel.valid_from.isoformat() if rel.valid_from else None,
        "valid_to": rel.valid_to.isoformat() if rel.valid_to else None,
        "evidence_count": supporting,
        "contradicting_count": contradicting,
        "best_grade": best_grade,
        "evidence_missing": supporting == 0,
    }


async def _write_payload(neo, payload: dict, run_id: str) -> None:
    query = f"""
    MERGE (s:Entity {{uid: $src_uid}})
      SET s += $src_props, s:{payload['src_label']},
          s.projected_at = datetime(), s.projection_run_id = $run_id
    MERGE (t:Entity {{uid: $tgt_uid}})
      SET t += $tgt_props, t:{payload['tgt_label']},
          t.projected_at = datetime(), t.projection_run_id = $run_id
    MERGE (s)-[r:{payload['cypher_type']} {{rid: $rid}}]->(t)
      SET r.status = $status,
          r.confidence = $confidence,
          r.valid_from = $valid_from,
          r.valid_to = $valid_to,
          r.evidence_count = $evidence_count,
          r.contradicting_count = $contradicting_count,
          r.evidence_grade_max = $best_grade,
          r.evidence_missing = $evidence_missing,
          r.projected_at = datetime()
    RETURN 1 AS ok
    """
    await neo.run(
        query,
        src_uid=payload["src_uid"],
        src_props=payload["src_props"],
        tgt_uid=payload["tgt_uid"],
        tgt_props=payload["tgt_props"],
        rid=payload["rid"],
        status=payload["status"],
        confidence=payload["confidence"],
        valid_from=payload["valid_from"],
        valid_to=payload["valid_to"],
        evidence_count=payload["evidence_count"],
        contradicting_count=payload["contradicting_count"],
        best_grade=payload["best_grade"],
        evidence_missing=payload["evidence_missing"],
        run_id=run_id,
    )


async def project_relationship(
    session: AsyncSession,
    relationship_id: uuid.UUID,
    *,
    run_id: str | None = None,
) -> ProjectionResult:
    """Project one relationship and both endpoints. Idempotent."""
    rel = (
        await session.execute(select(Relationship).where(Relationship.id == relationship_id))
    ).scalar_one_or_none()
    if rel is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "Relationship not found",
            details={"relationship_id": str(relationship_id)},
        )

    ok, reason = should_project(rel.relationship_type, rel.status)
    if not ok:
        return ProjectionResult(projected=False, reason=reason)

    payload = await _build_payload(session, rel)
    if payload is None:  # pragma: no cover - should_project already filtered
        return ProjectionResult(projected=False, reason="ineligible")

    driver = get_driver()
    async with driver.session() as neo:
        await _write_payload(neo, payload, run_id or "")

    return ProjectionResult(projected=True, reason="projected", nodes=2, edges=1)


# ---------------------------------------------------------------------------
# Full / incremental sweep
# ---------------------------------------------------------------------------


async def _eligible_relationships(
    session: AsyncSession, since: datetime | None
) -> list[Relationship]:
    stmt = select(Relationship).where(
        Relationship.status.in_([s.value for s in PROJECTABLE_STATUSES])
    )
    if since is not None:
        stmt = stmt.where(Relationship.updated_at > since)
    return list((await session.execute(stmt)).scalars().all())


async def _graph_rids(neo) -> set[str]:
    result = await neo.run("MATCH ()-[r]->() WHERE r.rid IS NOT NULL RETURN collect(r.rid) AS rids")
    record = await result.single()
    return set(record["rids"]) if record else set()


async def _clear_graph(neo) -> int:
    result = await neo.run("MATCH (n:Entity) DETACH DELETE n RETURN count(n) AS n")
    record = await result.single()
    return int(record["n"]) if record else 0


async def _node_count(neo) -> int:
    result = await neo.run("MATCH (n:Entity) RETURN count(n) AS n")
    record = await result.single()
    return int(record["n"]) if record else 0


async def project_all(
    session: AsyncSession,
    *,
    mode: str = "incremental",
    since: datetime | None = None,
) -> SweepResult:
    """Sweep the graph. `full` wipes and rebuilds; `incremental` touches only changed rows.

    Every sweep is recorded in graph_projection_run so a mismatch can be traced
    back to a specific run.
    """
    if mode not in {"full", "incremental"}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, f"unknown projection mode {mode}", details={"mode": mode}
        )

    run = GraphProjectionRun(mode=mode, started_at=datetime.now(UTC), status="running")
    session.add(run)
    await session.flush()
    run_id = str(run.id)
    result = SweepResult(run_id=run_id, mode=mode)

    try:
        driver = get_driver()
        async with driver.session() as neo:
            if mode == "full":
                await _clear_graph(neo)

            relationships = await _eligible_relationships(session, since)
            eligible_rids: set[str] = set()

            for rel in relationships:
                payload = await _build_payload(session, rel)
                if payload is None:
                    result.skipped.append(str(rel.id))
                    continue
                await _write_payload(neo, payload, run_id)
                eligible_rids.add(payload["rid"])
                result.edges_projected += 1

            # Prune edges that no longer qualify (e.g. rejected after being verified).
            stale = set() if mode == "full" else await _graph_rids(neo) - eligible_rids
            for rid in stale:
                result.edges_removed += await remove_relationship(uuid.UUID(rid))

            result.nodes = await _node_count(neo)

        run.finished_at = datetime.now(UTC)
        run.status = "succeeded"
        run.nodes_upserted = result.nodes
        run.edges_upserted = result.edges_projected
        run.edges_removed = result.edges_removed
        await session.flush()
        return result

    except Exception as exc:
        run.finished_at = datetime.now(UTC)
        run.status = "failed"
        run.detail = {"error": f"{type(exc).__name__}: {exc}"}
        await session.flush()
        raise


async def reconcile(session: AsyncSession) -> dict:
    """Compare what PostgreSQL says should be in the graph with what is there."""
    eligible = await _eligible_relationships(session, None)
    expected = {str(r.id) for r in eligible}

    driver = get_driver()
    async with driver.session() as neo:
        actual = await _graph_rids(neo)

    return {
        "expected_edges": len(expected),
        "actual_edges": len(actual),
        "missing": sorted(expected - actual),
        "extra": sorted(actual - expected),
        "consistent": expected == actual,
    }


async def remove_relationship(relationship_id: uuid.UUID) -> int:
    """Remove an edge from the graph (used when a relationship is rejected).

    The row in PostgreSQL is never deleted; only the projection disappears.
    """
    driver = get_driver()
    async with driver.session() as neo:
        result = await neo.run(
            "MATCH ()-[r {rid: $rid}]->() DELETE r RETURN count(r) AS removed",
            rid=str(relationship_id),
        )
        record = await result.single()
    return int(record["removed"]) if record else 0


async def fetch_edge(relationship_id: uuid.UUID) -> dict | None:
    """Read one projected edge back. Used by tests and by the consistency check."""
    driver = get_driver()
    async with driver.session() as neo:
        result = await neo.run(
            """
            MATCH (s:Entity)-[r {rid: $rid}]->(t:Entity)
            RETURN s.uid AS source, t.uid AS target, type(r) AS type,
                   properties(r) AS props
            """,
            rid=str(relationship_id),
        )
        record = await result.single()
    return dict(record) if record else None


async def graph_stats() -> dict:
    driver = get_driver()
    async with driver.session() as neo:
        nodes = await _node_count(neo)
        result = await neo.run("MATCH ()-[r]->() RETURN count(r) AS edges")
        record = await result.single()
    return {"nodes": nodes, "edges": int(record["edges"]) if record else 0}


async def purge_nodes(uids: list[str]) -> int:
    """Test helper: remove nodes (and their edges) by uid."""
    driver = get_driver()
    async with driver.session() as neo:
        result = await neo.run(
            "MATCH (n:Entity) WHERE n.uid IN $uids DETACH DELETE n RETURN count(n) AS n",
            uids=uids,
        )
        record = await result.single()
    return int(record["n"]) if record else 0


__all__ = [
    "ENTITY_LABELS",
    "PROJECTION_METADATA_KEYS",
    "RELATIONSHIP_TYPE_TO_CYPHER",
    "ProjectionResult",
    "SweepResult",
    "fetch_edge",
    "graph_stats",
    "project_all",
    "project_relationship",
    "purge_nodes",
    "reconcile",
    "remove_relationship",
    "should_project",
]

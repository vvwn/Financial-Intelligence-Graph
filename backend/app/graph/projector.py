"""The only writer of Neo4j (ADR-0001).

Scope of this module today: project ONE relationship (with its two endpoints) and
remove it. The full incremental/full projector (TASK-202) builds on these two
primitives; keeping them small makes the "graph is a projection" claim testable now.

Invariants enforced here:
  - candidate-layer types (POTENTIAL_*) are refused before any Cypher runs
  - only PROJECTABLE_STATUSES reach the graph
  - `disputed` is projected, but with status='disputed' so consumers cannot mistake
    it for established fact
  - MERGE everywhere, so projecting twice is a no-op
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.neo4j import get_driver
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.relationship import Relationship, RelationshipEvidence
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


async def _evidence_stats(session: AsyncSession, relationship_id: uuid.UUID) -> tuple[int, str | None]:
    """(independent origin count, strongest grade). Reposts of one origin count once."""
    stmt = (
        select(
            func.count(func.distinct(Evidence.origin_key)),
            func.min(Evidence.evidence_grade),
        )
        .join(RelationshipEvidence, RelationshipEvidence.evidence_id == Evidence.id)
        .where(
            RelationshipEvidence.relationship_id == relationship_id,
            RelationshipEvidence.relation == "supporting",
        )
    )
    count, best = (await session.execute(stmt)).one()
    return int(count or 0), best


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

    source = (
        await session.execute(select(Entity).where(Entity.id == rel.source_entity_id))
    ).scalar_one()
    target = (
        await session.execute(select(Entity).where(Entity.id == rel.target_entity_id))
    ).scalar_one()

    for entity in (source, target):
        if entity.entity_type not in ENTITY_LABELS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"entity_type {entity.entity_type} has no Neo4j label",
                details={"entity_id": str(entity.id)},
            )

    cypher_type = RELATIONSHIP_TYPE_TO_CYPHER[rel.relationship_type]
    evidence_count, best_grade = await _evidence_stats(session, relationship_id)

    query = f"""
    MERGE (s:Entity {{uid: $src_uid}})
      SET s += $src_props, s:{ENTITY_LABELS[source.entity_type]},
          s.projected_at = datetime(), s.projection_run_id = $run_id
    MERGE (t:Entity {{uid: $tgt_uid}})
      SET t += $tgt_props, t:{ENTITY_LABELS[target.entity_type]},
          t.projected_at = datetime(), t.projection_run_id = $run_id
    MERGE (s)-[r:{cypher_type} {{rid: $rid}}]->(t)
      SET r.status = $status,
          r.confidence = $confidence,
          r.valid_from = $valid_from,
          r.valid_to = $valid_to,
          r.evidence_count = $evidence_count,
          r.evidence_grade_max = $best_grade,
          r.evidence_missing = $evidence_missing,
          r.projected_at = datetime()
    RETURN 1 AS ok
    """

    driver = get_driver()
    async with driver.session() as neo:
        await neo.run(
            query,
            src_uid=str(source.id),
            src_props=_node_props(source),
            tgt_uid=str(target.id),
            tgt_props=_node_props(target),
            rid=str(rel.id),
            status=rel.status,
            confidence=float(rel.confidence),
            valid_from=rel.valid_from.isoformat() if rel.valid_from else None,
            valid_to=rel.valid_to.isoformat() if rel.valid_to else None,
            evidence_count=evidence_count,
            best_grade=best_grade,
            evidence_missing=evidence_count == 0,
            run_id=run_id or "",
        )

    return ProjectionResult(projected=True, reason="projected", nodes=2, edges=1)


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
    "fetch_edge",
    "project_relationship",
    "purge_nodes",
    "remove_relationship",
    "should_project",
]

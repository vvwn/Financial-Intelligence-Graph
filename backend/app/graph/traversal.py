"""Graph traversal: neighbours, paths, subgraph.

All limits are enforced here, not in the API layer, so no caller can bypass them:

  depth     <= 5      (DEPTH_LIMIT_EXCEEDED)
  nodes     <= 2000   (returns truncated=True instead of an error)
  statuses  default   {verified}; disputed only when explicitly requested

Disputed edges are excluded by default because they must not be read as fact
(see docs/graph-schema.md 5.1b).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from app.core.errors import AppError, ErrorCode
from app.core.neo4j import get_driver

Direction = Literal["up", "down", "both"]

MAX_DEPTH = 5
MAX_NODES = 2000
DEFAULT_NODES = 300


def _statuses(include_disputed: bool) -> list[str]:
    base = ["verified"]
    if include_disputed:
        base.append("disputed")
    return base


def _check_depth(depth: int) -> int:
    if depth < 1:
        raise AppError(ErrorCode.VALIDATION_ERROR, "depth must be >= 1", details={"depth": depth})
    if depth > MAX_DEPTH:
        raise AppError(
            ErrorCode.DEPTH_LIMIT_EXCEEDED,
            f"depth {depth} exceeds the maximum of {MAX_DEPTH}",
            details={"depth": depth, "max_depth": MAX_DEPTH},
        )
    return depth


def _check_limit(node_limit: int) -> int:
    if node_limit < 1:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "node_limit must be >= 1", details={"node_limit": node_limit}
        )
    if node_limit > MAX_NODES:
        raise AppError(
            ErrorCode.NODE_LIMIT_EXCEEDED,
            f"node_limit {node_limit} exceeds the maximum of {MAX_NODES}",
            details={"node_limit": node_limit, "max_nodes": MAX_NODES},
        )
    return node_limit


def _pattern(direction: Direction, depth: int) -> str:
    """Variable-length bounds cannot be parameterised, so depth is validated then inlined."""
    if direction == "down":
        return f"(start)-[rels*1..{depth}]->(other:Entity)"
    if direction == "up":
        return f"(start)<-[rels*1..{depth}]-(other:Entity)"
    return f"(start)-[rels*1..{depth}]-(other:Entity)"


def _edge_filter(relation_types: Iterable[str] | None) -> tuple[str, dict]:
    clauses = ["all(r IN rels WHERE r.status IN $statuses AND coalesce(r.confidence, 0.0) >= $min_conf)"]
    params: dict = {}
    if relation_types:
        types = [t.upper() for t in relation_types]
        clauses.append("all(r IN rels WHERE type(r) IN $rel_types)")
        params["rel_types"] = types
    return " AND ".join(clauses), params


async def _nodes_by_uids(neo, uids: list[str]) -> list[dict]:
    if not uids:
        return []
    result = await neo.run(
        """
        MATCH (n:Entity)
        WHERE n.uid IN $uids
        RETURN n.uid AS uid, labels(n) AS labels, properties(n) AS props
        """,
        uids=uids,
    )
    rows = []
    async for record in result:
        props = dict(record["props"])
        for key in ("projected_at", "projection_run_id"):
            props.pop(key, None)
        rows.append(
            {
                "id": record["uid"],
                "entity_type": props.get("entity_type"),
                "name": props.get("name"),
                "stock_code": props.get("stock_code"),
                "industry_code": props.get("industry_code"),
            }
        )
    return rows


async def _edges_among(neo, uids: list[str], statuses: list[str], min_conf: float) -> list[dict]:
    if not uids:
        return []
    result = await neo.run(
        """
        MATCH (a:Entity)-[r]->(b:Entity)
        WHERE a.uid IN $uids AND b.uid IN $uids
          AND r.status IN $statuses
          AND coalesce(r.confidence, 0.0) >= $min_conf
        RETURN a.uid AS source, b.uid AS target, type(r) AS type, properties(r) AS props
        """,
        uids=uids,
        statuses=statuses,
        min_conf=min_conf,
    )
    rows = []
    async for record in result:
        props = dict(record["props"])
        rows.append(
            {
                "relationship_id": props.get("rid"),
                "source": record["source"],
                "target": record["target"],
                "relationship_type": record["type"].lower(),
                "status": props.get("status"),
                "confidence": props.get("confidence"),
                "valid_from": props.get("valid_from"),
                "valid_to": props.get("valid_to"),
                "evidence_count": props.get("evidence_count", 0),
                "contradicting_count": props.get("contradicting_count", 0),
                "evidence_grade_max": props.get("evidence_grade_max"),
                "evidence_missing": props.get("evidence_missing", True),
            }
        )
    return rows


async def neighbors(
    node_uid: str,
    *,
    direction: Direction = "both",
    depth: int = 1,
    relation_types: list[str] | None = None,
    min_confidence: float = 0.0,
    include_disputed: bool = False,
    node_limit: int = DEFAULT_NODES,
) -> dict:
    """BFS around one node. Returns nodes, edges and a truncation flag."""
    depth = _check_depth(depth)
    node_limit = _check_limit(node_limit)
    statuses = _statuses(include_disputed)
    where, extra = _edge_filter(relation_types)

    query = f"""
    MATCH (start:Entity {{uid: $uid}})
    MATCH p = {_pattern(direction, depth)}
    WHERE {where}
    WITH other, min(length(p)) AS d
    ORDER BY d, other.uid
    LIMIT $limit
    RETURN collect(other.uid) AS uids, count(*) AS n, max(d) AS depth_used
    """

    driver = get_driver()
    async with driver.session() as neo:
        record = await (
            await neo.run(
                query,
                uid=node_uid,
                statuses=statuses,
                min_conf=min_confidence,
                limit=node_limit,
                **extra,
            )
        ).single()

        uids = list(record["uids"]) if record else []
        found = int(record["n"]) if record else 0
        depth_used = int(record["depth_used"] or 0) if record else 0

        all_uids = [node_uid, *uids]
        nodes = await _nodes_by_uids(neo, all_uids)
        edges = await _edges_among(neo, all_uids, statuses, min_confidence)

    if not any(n["id"] == node_uid for n in nodes):
        raise AppError(
            ErrorCode.NOT_FOUND,
            "Node not found in the graph",
            details={"node_id": node_uid},
        )

    return {
        "center": node_uid,
        "nodes": nodes,
        "edges": edges,
        "truncated": found >= node_limit,
        "node_limit": node_limit,
        "depth_used": depth_used,
    }


async def find_paths(
    from_uid: str,
    to_uid: str,
    *,
    max_depth: int = 3,
    include_disputed: bool = False,
    limit: int = 10,
) -> dict:
    """All simple paths between two nodes, shortest first."""
    max_depth = _check_depth(max_depth)
    statuses = _statuses(include_disputed)

    query = f"""
    MATCH (a:Entity {{uid: $from_uid}})
    MATCH (b:Entity {{uid: $to_uid}})
    MATCH p = (a)-[rels*1..{max_depth}]-(b)
    WHERE all(r IN rels WHERE r.status IN $statuses)
    RETURN [n IN nodes(p) | n.uid] AS uids,
           [r IN rels | {{rid: r.rid, type: type(r), status: r.status,
                          confidence: r.confidence}}] AS rels,
           length(p) AS depth
    ORDER BY depth, size(rels)
    LIMIT $limit
    """

    driver = get_driver()
    async with driver.session() as neo:
        result = await neo.run(
            query, from_uid=from_uid, to_uid=to_uid, statuses=statuses, limit=limit
        )
        raw = []
        all_uids: set[str] = set()
        async for record in result:
            raw.append(record)
            all_uids.update(record["uids"])

        nodes = {n["id"]: n for n in await _nodes_by_uids(neo, list(all_uids))}

    paths = []
    for record in raw:
        rels = [dict(r) for r in record["rels"]]
        for rel in rels:
            rel["relationship_type"] = rel.pop("type").lower()
        paths.append(
            {
                "nodes": [nodes.get(uid) for uid in record["uids"]],
                "relationships": rels,
                "depth": int(record["depth"]),
                "min_confidence": min(
                    (r.get("confidence") or 0.0 for r in rels), default=0.0
                ),
            }
        )

    return {"from": from_uid, "to": to_uid, "paths": paths, "max_depth": max_depth}


async def subgraph(
    *,
    industry_code: str | None = None,
    entity_types: list[str] | None = None,
    status: str = "verified",
    include_disputed: bool = False,
    min_confidence: float = 0.0,
    node_limit: int = DEFAULT_NODES,
) -> dict:
    """First-screen subgraph: a closed neighbourhood filtered by industry or type."""
    node_limit = _check_limit(node_limit)
    statuses = _statuses(include_disputed)
    if status not in statuses:
        statuses = [status]

    filters = []
    params: dict = {"limit": node_limit, "statuses": statuses, "min_conf": min_confidence}
    if industry_code:
        filters.append("n.industry_code = $industry_code")
        params["industry_code"] = industry_code
    if entity_types:
        filters.append("n.entity_type IN $entity_types")
        params["entity_types"] = entity_types

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    query = f"""
    MATCH (n:Entity)
    {where}
    WITH n ORDER BY n.name LIMIT $limit
    RETURN collect(n.uid) AS uids, count(*) AS n
    """

    driver = get_driver()
    async with driver.session() as neo:
        record = await (await neo.run(query, **params)).single()
        uids = list(record["uids"]) if record else []
        found = int(record["n"]) if record else 0
        nodes = await _nodes_by_uids(neo, uids)
        edges = await _edges_among(neo, uids, statuses, min_confidence)

    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": found >= node_limit,
        "node_limit": node_limit,
        "filters": {
            "industry_code": industry_code,
            "entity_types": entity_types,
            "status": status,
            "min_confidence": min_confidence,
        },
    }


__all__ = [
    "DEFAULT_NODES",
    "MAX_DEPTH",
    "MAX_NODES",
    "find_paths",
    "neighbors",
    "subgraph",
]

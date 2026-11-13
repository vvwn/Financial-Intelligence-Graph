"""Graph read endpoints (contract 6.6). Read-only; only the projector writes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.graph import traversal
from app.schemas.api import Envelope, GraphView, PathView
from app.schemas.envelope import ok

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/subgraph", response_model=Envelope[GraphView], summary="首屏子图")
async def get_subgraph(
    request: Request,
    industry_code: str | None = None,
    entity_types: list[str] | None = Query(None),
    status: str = "verified",
    include_disputed: bool = False,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    node_limit: int = Query(traversal.DEFAULT_NODES, ge=1),
) -> dict:
    view = await traversal.subgraph(
        industry_code=industry_code,
        entity_types=entity_types,
        status=status,
        include_disputed=include_disputed,
        min_confidence=min_confidence,
        node_limit=node_limit,
    )
    return ok(
        request,
        view,
        truncated=view["truncated"],
        extra={"node_limit": view["node_limit"], "filters": view["filters"]},
    )


@router.get("/neighbors", response_model=Envelope[GraphView], summary="邻域遍历")
async def get_neighbors(
    request: Request,
    node_id: str,
    direction: str = Query("both", pattern="^(up|down|both)$"),
    depth: int = Query(1, ge=1),
    relation_types: list[str] | None = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    include_disputed: bool = False,
    node_limit: int = Query(traversal.DEFAULT_NODES, ge=1),
) -> dict:
    view = await traversal.neighbors(
        node_id,
        direction=direction,  # type: ignore[arg-type]
        depth=depth,
        relation_types=relation_types,
        min_confidence=min_confidence,
        include_disputed=include_disputed,
        node_limit=node_limit,
    )
    return ok(
        request,
        view,
        truncated=view["truncated"],
        extra={"node_limit": view["node_limit"], "depth_used": view["depth_used"]},
    )


@router.get("/path", response_model=Envelope[PathView], summary="两点间路径")
async def get_path(
    request: Request,
    from_: str = Query(alias="from"),
    to: str = Query(),
    max_depth: int = Query(3, ge=1),
    include_disputed: bool = False,
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    result = await traversal.find_paths(
        from_, to, max_depth=max_depth, include_disputed=include_disputed, limit=limit
    )
    return ok(
        request,
        {
            "from": result["from"],
            "to": result["to"],
            "paths": result["paths"],
            "max_depth": result["max_depth"],
        },
    )


__all__ = ["router"]

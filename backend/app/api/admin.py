"""Admin endpoints for the graph projection (contract 6.11).

These are the only places that can trigger a sweep. Keeping them under /admin
makes it obvious they are operator actions, not business endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.graph import projector
from app.schemas.envelope import ok

router = APIRouter(prefix="/admin/graph", tags=["admin"])


@router.post("/project", summary="触发投影（full / incremental）")
async def run_projection(
    request: Request,
    mode: str = Query("incremental", pattern="^(full|incremental)$"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await projector.project_all(session, mode=mode)
    await session.commit()
    return ok(
        request,
        {
            "run_id": result.run_id,
            "mode": result.mode,
            "nodes": result.nodes,
            "edges_projected": result.edges_projected,
            "edges_removed": result.edges_removed,
            "skipped": result.skipped,
        },
    )


@router.get("/reconcile", summary="PG 应入图 vs 图中实际")
async def reconcile(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    return ok(request, await projector.reconcile(session))


@router.get("/stats", summary="图规模")
async def stats(request: Request) -> dict:
    return ok(request, await projector.graph_stats())


__all__ = ["router"]

"""API v1 router assembly.

Business endpoints live under /api/v1 (contract base path).
Probe endpoints (/health, /ready) are mounted at the root on purpose: monitoring
systems expect them unversioned, and they are not part of the business contract.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import admin, entities, evidence, graph, relationships

api_router = APIRouter()
api_router.include_router(entities.router)
api_router.include_router(evidence.router)
api_router.include_router(relationships.router)
api_router.include_router(graph.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]

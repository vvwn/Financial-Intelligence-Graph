"""API v1 router assembly.

Only endpoints that exist are mounted here. Adding a router requires the
contract to be frozen first (AGENTS.md rule 2 / 6).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router"]

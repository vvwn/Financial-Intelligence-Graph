"""API v1 router assembly.

Business endpoints live under /api/v1 (contract base path).
Probe endpoints (/health, /ready) are mounted at the root on purpose: monitoring
systems expect them unversioned, and they are not part of the business contract.
"""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()

__all__ = ["api_router"]

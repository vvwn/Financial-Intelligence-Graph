"""Response envelope helpers — docs/api-contracts.md section 2.

Every endpoint returns either:
    {"data": ..., "meta": {...}}
or
    {"error": {...}}
Never a bare payload at the top level.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Request


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _request_id(request: Request | None) -> str:
    if request is None:
        return ""
    return getattr(request.state, "request_id", "")


def meta(
    request: Request | None = None,
    *,
    next_cursor: str | None = None,
    truncated: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": _request_id(request),
        "generated_at": now_iso(),
    }
    if next_cursor is not None:
        payload["next_cursor"] = next_cursor
    if truncated is not None:
        payload["truncated"] = truncated
    if extra:
        payload.update(extra)
    return payload


def ok(
    request: Request | None,
    data: Any,
    **meta_kwargs: Any,
) -> dict[str, Any]:
    """Success envelope."""
    return {"data": data, "meta": meta(request, **meta_kwargs)}


def error_body(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Failure envelope."""
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details or {},
        "request_id": request_id,
    }
    return {"error": body}


__all__ = ["error_body", "meta", "now_iso", "ok"]

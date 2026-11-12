"""Request-scoped context. Lets the logger attach request_id without threading it through."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return request_id_var.get()


__all__ = ["current_request_id", "request_id_var"]

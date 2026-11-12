"""Error codes and application exception.

The code set is CLOSED — see docs/api-contracts.md section 2.3.
Adding a code requires editing the contract first.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DEPTH_LIMIT_EXCEEDED = "DEPTH_LIMIT_EXCEEDED"
    NODE_LIMIT_EXCEEDED = "NODE_LIMIT_EXCEEDED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    STATE_TRANSITION_INVALID = "STATE_TRANSITION_INVALID"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    CLAIM_TYPE_NOT_PROMOTABLE = "CLAIM_TYPE_NOT_PROMOTABLE"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    DEPENDENCY_NOT_READY = "DEPENDENCY_NOT_READY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.DEPTH_LIMIT_EXCEEDED: 400,
    ErrorCode.NODE_LIMIT_EXCEEDED: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.STATE_TRANSITION_INVALID: 409,
    ErrorCode.EVIDENCE_REQUIRED: 422,
    ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_UNAVAILABLE: 502,
    ErrorCode.DEPENDENCY_NOT_READY: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    """Raise this anywhere; the global handler turns it into the error envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code or HTTP_STATUS[code]


__all__ = ["AppError", "ErrorCode", "HTTP_STATUS"]

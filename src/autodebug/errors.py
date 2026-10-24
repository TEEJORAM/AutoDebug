"""Stable, versioned error codes for AutoDebug's MCP contract (T01 scaffold).

AutoDebug components raise `AutoDebugError` with one of these codes instead of an
ad-hoc message, so every caller can branch on a bounded, documented set
(see docs/mcp-contract.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    SESSION_AMBIGUOUS = "SESSION_AMBIGUOUS"
    SESSION_STALE = "SESSION_STALE"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    NOT_APPROVED = "NOT_APPROVED"
    PLAN_CHANGED = "PLAN_CHANGED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    BREAKPOINT_UNBOUND = "BREAKPOINT_UNBOUND"
    NOT_PAUSED = "NOT_PAUSED"
    TIMEOUT = "TIMEOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    POLICY_LIMIT = "POLICY_LIMIT"
    SENSITIVE_OUTPUT_BLOCKED = "SENSITIVE_OUTPUT_BLOCKED"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class ErrorDetail:
    code: ErrorCode
    message: str
    recoverable: bool = False


class AutoDebugError(Exception):
    """Raised by AutoDebug components; carries a stable `ErrorDetail` so callers
    branch on `error.detail.code`, not on message text."""

    def __init__(self, detail: ErrorDetail) -> None:
        super().__init__(detail.message)
        self.detail = detail

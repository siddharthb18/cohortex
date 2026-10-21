"""Structured tool errors (implementation-notes §6, FR-TOOL-2).

A failed call is an MCP tool result with ``isError: true`` whose text and ``structuredContent``
are ``{"error": {"code": ..., "message": ...}}``. Messages are short, never contain stack traces,
and never echo caller-supplied strings (so injected text cannot ride back into the prompt).
"""

from __future__ import annotations

import re
from typing import Any, Literal

ErrorCode = Literal["invalid_argument", "not_found", "upstream_error", "too_large"]
ERROR_CODES: tuple[ErrorCode, ...] = (
    "invalid_argument",
    "not_found",
    "upstream_error",
    "too_large",
)
MAX_MESSAGE_CHARS = 300

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_message(text: str) -> str:
    """Strip control characters, collapse whitespace and cap the length."""
    collapsed = " ".join(_CONTROL.sub(" ", text).split())
    if len(collapsed) > MAX_MESSAGE_CHARS:
        return collapsed[: MAX_MESSAGE_CHARS - 3] + "..."
    return collapsed


class ToolError(Exception):
    """An expected tool failure, reported to the caller as a structured error body."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = clean_message(message)

    def body(self) -> dict[str, Any]:
        """The JSON error body."""
        return {"error": {"code": self.code, "message": self.message}}

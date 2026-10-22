"""Helpers for JSON outputs: parse leniently, validate strictly with Pydantic."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

JSON_MODE: dict[str, Any] = {"type": "json_object"}
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Parse a JSON object, tolerating a Markdown code fence around it."""
    if not text or not text.strip():
        raise ValueError("empty output; expected a JSON object")
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(body[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object at the top level")
    return value


def validate_output[M: BaseModel](text: str | None, model: type[M]) -> tuple[M | None, str]:
    """Return (instance, "") or (None, a short error description for the repair prompt)."""
    try:
        data = parse_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, f"not a JSON object: {exc}"
    try:
        return model.model_validate(data), ""
    except ValidationError as exc:
        lines = [
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()[:12]
        ]
        return None, "; ".join(lines)

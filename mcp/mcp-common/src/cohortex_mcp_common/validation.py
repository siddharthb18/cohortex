"""Validate tool arguments against the contract JSON Schema before anything else runs (FR-TOOL-2).

Error messages are built from the *schema* (property names, bounds, enum values), never from the
caller's values, so oversized or injected strings are not echoed back to the model.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]

from cohortex_mcp_common.errors import ToolError

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_]")
_BOUND_WORDS = {
    "maxLength": "at most {} characters",
    "minLength": "at least {} characters",
    "maximum": "at most {}",
    "minimum": "at least {}",
    "exclusiveMaximum": "less than {}",
    "exclusiveMinimum": "greater than {}",
    "maxItems": "at most {} items",
    "minItems": "at least {} items",
}


def _path_label(path: Iterable[Any]) -> str:
    parts = []
    for segment in path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            safe = _SAFE_SEGMENT.sub("", str(segment))[:40]
            parts.append(f".{safe}" if parts else safe)
    return "".join(parts) or "arguments"


def _has_non_finite(value: Any, depth: int = 0) -> bool:
    if depth > 20:
        return True  # absurd nesting is rejected along with NaN/Infinity
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_has_non_finite(v, depth + 1) for v in value)
    return False


def _describe(error: Any) -> str:
    label = _path_label(error.absolute_path)
    keyword = str(error.validator)
    expected = error.validator_value
    if keyword == "additionalProperties":
        allowed = sorted(cast(dict[str, Any], error.schema.get("properties", {})))
        return f"{label} has unexpected keys; allowed keys: {', '.join(allowed)}"
    if keyword == "required":
        instance = error.instance if isinstance(error.instance, dict) else {}
        missing = [str(name) for name in expected if name not in instance]
        return f"{label} is missing required key(s): {', '.join(missing)}"
    if keyword == "type":
        return f"{label} must be of type {expected}"
    if keyword == "enum":
        return f"{label} must be one of: {', '.join(str(v) for v in expected)}"
    if keyword == "pattern":
        return f"{label} contains characters or a layout that is not allowed"
    if keyword == "format":
        return f"{label} must be a valid {expected} (YYYY-MM-DD)"
    if keyword in _BOUND_WORDS:
        return f"{label} must be {_BOUND_WORDS[keyword].format(expected)}"
    return f"{label} is not valid ({keyword})"


def _normalize(schema: dict[str, Any], value: Any) -> Any:
    """Apply top-level defaults and turn integral floats into ints where the schema says integer."""
    kind = schema.get("type")
    if kind == "integer" and isinstance(value, float):
        return int(value)
    if kind == "object" and isinstance(value, dict):
        props = cast(dict[str, dict[str, Any]], schema.get("properties", {}))
        out = {key: _normalize(props.get(key, {}), item) for key, item in value.items()}
        for key, prop in props.items():
            if key not in out and "default" in prop:
                out[key] = prop["default"]
        return out
    if kind == "array" and isinstance(value, list):
        items = cast(dict[str, Any], schema.get("items", {}))
        return [_normalize(items, item) for item in value]
    return value


class ArgumentValidator:
    """Compiled validator for one tool's input schema."""

    def __init__(self, schema: dict[str, Any]) -> None:
        Draft202012Validator.check_schema(schema)
        self._schema = schema
        self._validator = Draft202012Validator(
            schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )

    def validate(self, arguments: Any) -> dict[str, Any]:
        """Return the arguments with defaults applied, or raise ``ToolError(invalid_argument)``."""
        if arguments is None:
            arguments = {}
        if _has_non_finite(arguments):
            raise ToolError("invalid_argument", "arguments contain NaN, Infinity or deep nesting")
        error = best_match(self._validator.iter_errors(arguments))
        if error is not None:
            raise ToolError("invalid_argument", _describe(error))
        return cast(dict[str, Any], _normalize(self._schema, arguments))

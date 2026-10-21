"""FR-TOOL-2 and FR-TOOL-4: bounded schemas, structured errors that never echo input."""

from typing import Any

import pytest
from cohortex_mcp_common.contracts import contracts_dir, load_input_schema, load_json
from cohortex_mcp_common.errors import ToolError, clean_message
from cohortex_mcp_common.validation import ArgumentValidator

INJECTION = "x'; DROP TABLE drive; --"


def _all_schemas() -> list[tuple[str, dict[str, Any]]]:
    manifest = load_json(contracts_dir() / "tools" / "manifest.json")
    return [
        (f"{t['server']}.{t['name']}", load_input_schema(t["server"], t["name"]))
        for t in manifest["tools"]
    ]


def _walk(schema: dict[str, Any]) -> list[dict[str, Any]]:
    found = [schema]
    for prop in schema.get("properties", {}).values():
        found.extend(_walk(prop))
    if isinstance(schema.get("items"), dict):
        found.extend(_walk(schema["items"]))
    return found


@pytest.mark.parametrize(("name", "schema"), _all_schemas())
def test_schemas_are_bounded(name: str, schema: dict[str, Any]) -> None:
    """Static FR-TOOL-4 check: every string is enum/pattern+maxLength, numbers bounded."""
    for node in _walk(schema):
        kind = node.get("type")
        if kind == "object":
            assert node.get("additionalProperties") is False, name
        elif kind == "string":
            assert "enum" in node or ("pattern" in node and "maxLength" in node), name
        elif kind in ("integer", "number"):
            assert "enum" in node or ("minimum" in node and "maximum" in node), name
        elif kind == "array":
            assert "maxItems" in node, name
        else:
            pytest.fail(f"{name}: unbounded node {node}")


def test_defaults_applied_and_integral_floats_normalized() -> None:
    validator = ArgumentValidator(load_input_schema("stats", "afr_ci"))
    args = validator.validate({"failures": 3.0, "drive_days": 100})
    assert args == {"failures": 3, "drive_days": 100, "confidence": 0.95}
    assert isinstance(args["failures"], int)


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        [],
        "text",
        {"failures": "3", "drive_days": 1},
        {"failures": True, "drive_days": 1},
        {"failures": -1, "drive_days": 1},
        {"failures": 1, "drive_days": 0},
        {"failures": 1, "drive_days": 1, "sql": "SELECT 1"},
        {"failures": 1.5, "drive_days": 1},
        {"failures": 1, "drive_days": 1, "confidence": float("nan")},
        {"failures": 1, "drive_days": 1, "confidence": 1.5},
    ],
)
def test_invalid_stats_arguments(arguments: Any) -> None:
    validator = ArgumentValidator(load_input_schema("stats", "afr_ci"))
    with pytest.raises(ToolError) as info:
        validator.validate(arguments)
    assert info.value.code == "invalid_argument"


@pytest.mark.parametrize(
    "model",
    [
        INJECTION,
        "1 OR 1=1",
        "ST12000 --",
        "../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\system.ini",
        "https://evil.example/x",
        "file:///etc/passwd",
        "A" * 65,
        "",
        " leading-space",
        "model\nwith newline",
    ],
)
def test_injection_strings_rejected_without_echo(model: str) -> None:
    validator = ArgumentValidator(load_input_schema("fleet", "cohort_afr"))
    args = {"source": "backblaze", "model": model, "from": "2026-04-01", "to": "2026-06-30"}
    with pytest.raises(ToolError) as info:
        validator.validate(args)
    assert info.value.code == "invalid_argument"
    if len(model) > 3:
        assert model not in info.value.message


@pytest.mark.parametrize("bad", ["2026-02-30", "20260401", "2026-4-1", "1999-01-01", "now()"])
def test_bad_dates_rejected(bad: str) -> None:
    validator = ArgumentValidator(load_input_schema("fleet", "fleet_summary"))
    with pytest.raises(ToolError):
        validator.validate({"source": "backblaze", "from": bad, "to": "2026-06-30"})


def test_unexpected_keys_message_lists_allowed_not_given() -> None:
    validator = ArgumentValidator(load_input_schema("fleet", "fleet_summary"))
    with pytest.raises(ToolError) as info:
        validator.validate(
            {"source": "backblaze", "from": "2026-04-01", "to": "2026-06-30", INJECTION: 1}
        )
    assert "allowed keys: from, source, to" in info.value.message
    assert "DROP" not in info.value.message


def test_clean_message_strips_control_and_caps_length() -> None:
    assert clean_message("a\n\tb") == "a b"
    assert len(clean_message("x" * 1000)) == 300

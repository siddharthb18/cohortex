"""Generated contracts stay in sync with the code (`python -m cohortex_agent.contracts_export`)."""

from __future__ import annotations

import json

from cohortex_agent.contracts_export import (
    OPENAPI_PATH,
    REPORT_SCHEMA_PATH,
    main,
    openapi_text,
    report_schema_text,
)


def test_committed_report_schema_matches_the_report_model() -> None:
    assert REPORT_SCHEMA_PATH.read_text(encoding="utf-8") == report_schema_text()
    schema = json.loads(report_schema_text())
    assert schema["title"] == "Report"
    assert set(schema["required"]) >= {"summary", "findings", "limitations", "unverified"}
    assert schema["properties"]["summary"]["maxItems"] == 5
    assert set(schema["$defs"]["NumberRef"]["properties"]["unit"]["enum"]) == {
        "pct",
        "count",
        "drive_days",
        "days",
        "ratio",
        "p_value",
        "raw",
    }


def test_committed_openapi_matches_the_app() -> None:
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_text()
    spec = json.loads(openapi_text().split("\n", 1)[1])
    assert spec["openapi"].startswith("3.1")
    paths = set(spec["paths"])
    assert {
        "/v1/investigations",
        "/v1/investigations/{investigation_id}",
        "/v1/investigations/{investigation_id}/events",
        "/v1/investigations/{investigation_id}/evidence/{evidence_id}",
        "/v1/alerts/suggested",
        "/v1/evals/latest",
        "/healthz",
        "/readyz",
    } <= paths


def test_check_mode_passes_when_in_sync() -> None:
    assert main(["--check"]) == 0

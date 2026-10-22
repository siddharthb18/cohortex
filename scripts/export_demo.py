"""Export real data for the web UI's static demo mode (services/web-ui/public/demo/).

Reads one or more completed investigations (with steps and evidence) and the serving tables from
Postgres, plus the compare ranking from fleet-api, and writes the JSON files demo mode replays.

    uv run python scripts/export_demo.py --investigation <id> [--investigation <id> ...]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

OUT = Path(__file__).resolve().parents[1] / "services" / "web-ui" / "public" / "demo"
NOTE = (
    "Real data: Backblaze Drive Stats {period} (courtesy of Backblaze), loaded by ingest-batch; "
    "investigations recorded live with {model} on the Groq free tier."
)


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if hasattr(value, "is_finite"):  # Decimal
        return float(value)
    return value


def investigation(conn: psycopg.Connection[dict[str, Any]], inv_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id::text, question, scope, mode, status, llm_model, started_at, finished_at,"
        " tokens_in, tokens_out, cost_usd, report FROM investigation WHERE id = %s",
        (inv_id,),
    ).fetchone()
    if row is None or row["status"] != "completed":
        raise SystemExit(f"investigation {inv_id} is missing or not completed")
    steps = conn.execute(
        "SELECT seq, node, kind, payload, started_at, ended_at FROM investigation_step"
        " WHERE investigation_id = %s ORDER BY seq",
        (inv_id,),
    ).fetchall()
    evidence = conn.execute(
        "SELECT evidence_id, tool_name AS tool, args, result, created_at FROM evidence"
        " WHERE investigation_id = %s",
        (inv_id,),
    ).fetchall()
    agent_api = os.environ.get("AGENT_API_URL", "http://localhost:8000")
    with urllib.request.urlopen(f"{agent_api}/v1/investigations/{inv_id}") as response:  # noqa: S310
        detail = json.load(response)  # same shape the live UI reads, markdown included
    return jsonable(
        {
            "detail": detail,
            "steps": [dict(s) for s in steps],
            "evidence": {e["evidence_id"]: dict(e) for e in evidence},
        }
    )


def fleet(conn: psycopg.Connection[dict[str, Any]], top: int) -> dict[str, list[dict[str, Any]]]:
    sources: dict[str, list[dict[str, Any]]] = {}
    for source in ("backblaze", "alibaba"):
        models = conn.execute(
            "SELECT m.id, m.model, m.media, m.capacity_bytes, sum(c.drive_days) AS dd"
            " FROM drive_model m JOIN (SELECT model_id, sum(drive_count) AS drive_days"
            " FROM cohort_daily GROUP BY model_id) c ON c.model_id = m.id"
            " WHERE m.source = %s GROUP BY m.id ORDER BY dd DESC LIMIT %s",
            (source, top),
        ).fetchall()
        out = []
        for m in models:
            months = conn.execute(
                "SELECT to_char(day, 'YYYY-MM') AS period, sum(drive_count)::bigint AS drive_days,"
                " sum(failures)::int AS failures,"
                " (array_agg(drive_count ORDER BY day DESC))[1] AS drives"
                " FROM cohort_daily WHERE model_id = %s GROUP BY 1 ORDER BY 1",
                (m["id"],),
            ).fetchall()
            age = conn.execute(
                "SELECT coalesce(avg(%s::date - first_seen), 0)::int AS age FROM drive"
                " WHERE model_id = %s",
                (months[0]["period"] + "-01", m["id"]),
            ).fetchone()
            out.append(
                {
                    "model": m["model"],
                    "media": m["media"],
                    "capacity_bytes": m["capacity_bytes"],
                    "months": [dict(x) for x in months],
                    "base_age_days": max(0, int(age["age"] if age else 0)),
                }
            )
        sources[source] = out
    return sources


def compare(fleet_api: str, source: str, date_from: str, date_to: str) -> dict[str, Any]:
    params = {"source": source, "from": date_from, "to": date_to, "limit": 50}
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{fleet_api}/v1/cohorts/compare?{query}") as response:  # noqa: S310
        body: dict[str, Any] = json.load(response)
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--investigation", action="append", required=True)
    parser.add_argument("--top", type=int, default=40, help="models per source in fleet-data.json")
    parser.add_argument("--from", dest="date_from", default="2026-04-01")
    parser.add_argument("--to", dest="date_to", default="2026-06-30")
    parser.add_argument("--period", default="Q2 2026")
    args = parser.parse_args()

    fleet_api = os.environ.get("FLEET_API_URL", "http://localhost:8080")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        runs = [investigation(conn, i) for i in args.investigation]
        sources = fleet(conn, args.top)
    model_id = runs[0]["detail"]["llm_model"]
    note = NOTE.format(period=args.period, model=model_id)
    now = datetime.now(UTC).isoformat()

    OUT.mkdir(parents=True, exist_ok=True)
    first = runs[0]
    (OUT / "investigation.json").write_text(json.dumps({"note": note, **first}, indent=1))
    summaries = [
        {k: r["detail"][k] for k in ("id", "question", "mode", "status")}
        | {k: r["detail"][k] for k in ("started_at", "finished_at")}
        for r in runs
    ]
    (OUT / "investigations.json").write_text(json.dumps(summaries, indent=1))
    (OUT / "fleet-data.json").write_text(
        json.dumps({"note": note, "generated_at": now, "sources": sources}, indent=1)
    )
    canned = [compare(fleet_api, "backblaze", args.date_from, args.date_to)]
    (OUT / "fleet-compare.json").write_text(json.dumps(canned, indent=1))
    (OUT / "alerts.json").write_text("[]\n")
    print(f"wrote demo files to {OUT}")


if __name__ == "__main__":
    main()

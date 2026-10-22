"""In-memory tool gateway with contracts §5 shapes, for tests and offline demos.

`COHORTEX_TOOLS_BACKEND=fake` serves this fixture instead of the MCP servers. The numbers are a
small, self-consistent fixture (AFR = failures x 365 x 100 / drive_days); they are not truth.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from cohortex_agent.tools.base import ToolCallError, ToolSpec

Handler = Callable[[dict[str, Any]], Any]

_DATE = {"type": "string", "format": "date"}
_SOURCE = {"type": "string", "enum": ["backblaze", "alibaba"]}
_MODEL = {"type": "string", "pattern": "^[A-Za-z0-9_.\\- ]{1,64}$"}


def _obj(required: list[str], **props: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": props,
    }


DEFAULT_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "fleet",
        "list_models",
        "List drive models of a source with media, capacity and current drive count.",
        _obj(
            ["source"],
            source=_SOURCE,
            media={"type": "string", "enum": ["hdd", "ssd"]},
            min_drives={"type": "integer", "minimum": 0},
        ),
    ),
    ToolSpec(
        "fleet",
        "cohort_afr",
        "AFR series (percent) with exact Poisson 95% CI, drive_days and failures for one model.",
        _obj(
            ["source", "model", "from", "to"],
            source=_SOURCE,
            model=_MODEL,
            **{"from": _DATE, "to": _DATE},
            granularity={"type": "string", "enum": ["quarter", "month"]},
        ),
    ),
    ToolSpec(
        "fleet",
        "compare_cohorts",
        "Rank models in a window by AFR (percent) with CI and rate ratio vs the fleet.",
        _obj(
            ["source", "from", "to"],
            source=_SOURCE,
            **{"from": _DATE, "to": _DATE},
            min_drives={"type": "integer", "minimum": 0},
            limit={"type": "integer", "minimum": 1, "maximum": 20},
        ),
    ),
    ToolSpec(
        "fleet",
        "fleet_summary",
        "Fleet totals for a window: drives, drive_days, failures, AFR (percent) with CI.",
        _obj(["source", "from", "to"], source=_SOURCE, **{"from": _DATE, "to": _DATE}),
    ),
    ToolSpec(
        "fleet",
        "smart_trend",
        "p50, p95 and non-zero share of one SMART attribute by period (1% sample).",
        _obj(
            ["source", "model", "attr", "from", "to"],
            source=_SOURCE,
            model=_MODEL,
            attr={"type": "integer"},
            **{"from": _DATE, "to": _DATE},
        ),
    ),
    ToolSpec(
        "fleet",
        "failed_drives",
        "Failed drives of a model with age at failure (days) and last SMART values.",
        _obj(
            ["source", "model", "from", "to"],
            source=_SOURCE,
            model=_MODEL,
            **{"from": _DATE, "to": _DATE},
            page={"type": "integer", "minimum": 0},
        ),
    ),
    ToolSpec(
        "stats",
        "afr_ci",
        "AFR (percent) with an exact Poisson confidence interval.",
        _obj(
            ["failures", "drive_days"],
            failures={"type": "integer", "minimum": 0},
            drive_days={"type": "integer", "minimum": 1},
            confidence={"type": "number"},
        ),
    ),
    ToolSpec(
        "stats",
        "compare_rates",
        "Rate ratio of two Poisson rates with CI and exact conditional binomial p-value.",
        _obj(
            ["failures_a", "drive_days_a", "failures_b", "drive_days_b"],
            failures_a={"type": "integer", "minimum": 0},
            drive_days_a={"type": "integer", "minimum": 1},
            failures_b={"type": "integer", "minimum": 0},
            drive_days_b={"type": "integer", "minimum": 1},
        ),
    ),
    ToolSpec(
        "stats",
        "change_point",
        "Most likely single change point in a failure-rate series.",
        _obj(["series"], series={"type": "array", "maxItems": 60}),
    ),
    ToolSpec(
        "docs",
        "search",
        "Hybrid search over the reliability corpus; returns passages with snippets.",
        _obj(
            ["query"],
            query={"type": "string", "maxLength": 300},
            k={"type": "integer", "maximum": 8},
        ),
    ),
    ToolSpec(
        "docs",
        "get_passage",
        "Fetch one passage (at most 1,200 characters) with its citation.",
        _obj(["passage_id"], passage_id={"type": "string"}),
    ),
)

# model -> period -> (drive_days, failures)
FIXTURE_COHORTS: dict[str, dict[str, tuple[int, int]]] = {
    "ST12000NM000J": {"2026Q1": (98_010, 2), "2026Q2": (98_189, 9)},
    "ST16000NM001G": {"2026Q1": (1_201_220, 41), "2026Q2": (1_210_515, 44)},
    "HUH721212ALE604": {"2026Q1": (912_400, 12), "2026Q2": (905_100, 11)},
}
FIXTURE_DRIVES = {"ST12000NM000J": 1_079, "ST16000NM001G": 13_301, "HUH721212ALE604": 9_946}


def afr_pct(failures: int, drive_days: int) -> float:
    return round(failures * 365 * 100 / drive_days, 4)


def _approx_ci(failures: int, drive_days: int) -> tuple[float, float]:
    """Rough interval for the fixture only (the real servers use the exact Poisson method)."""
    low = max(0.0, failures - 1.96 * failures**0.5)
    high = failures + 1.96 * (failures + 1) ** 0.5 + 1
    return afr_pct(round(low), drive_days), afr_pct(round(high), drive_days)


def _periods(args: dict[str, Any]) -> list[str]:
    start, end = str(args.get("from", "2026-01-01")), str(args.get("to", "2026-06-30"))
    periods = []
    if start <= "2026-03-31" and end >= "2026-01-01":
        periods.append("2026Q1")
    if start <= "2026-06-30" and end >= "2026-04-01":
        periods.append("2026Q2")
    return periods


def _cohort_afr(args: dict[str, Any]) -> Any:
    model = str(args["model"])
    if model not in FIXTURE_COHORTS:
        raise ToolCallError("not_found", f"unknown model {model}")
    series = []
    for period in _periods(args):
        drive_days, failures = FIXTURE_COHORTS[model][period]
        low, high = _approx_ci(failures, drive_days)
        series.append(
            {
                "period": period,
                "drive_days": drive_days,
                "failures": failures,
                "afr_pct": afr_pct(failures, drive_days),
                "ci_low_pct": low,
                "ci_high_pct": high,
            }
        )
    return {
        "source": args["source"],
        "model": model,
        "series": series,
        "method": "exact_poisson_95",
    }


def _totals(args: dict[str, Any]) -> dict[str, tuple[int, int]]:
    periods = _periods(args)
    return {
        model: (
            sum(by_period[p][0] for p in periods),
            sum(by_period[p][1] for p in periods),
        )
        for model, by_period in FIXTURE_COHORTS.items()
    }


def _compare(args: dict[str, Any]) -> Any:
    totals = _totals(args)
    fleet_dd = sum(dd for dd, _ in totals.values())
    fleet_f = sum(f for _, f in totals.values())
    fleet_afr = afr_pct(fleet_f, fleet_dd)
    rows: list[dict[str, Any]] = []
    for model, (dd, f) in totals.items():
        if FIXTURE_DRIVES[model] < int(args.get("min_drives", 60)):
            continue
        low, high = _approx_ci(f, dd)
        rows.append(
            {
                "model": model,
                "drive_days": dd,
                "failures": f,
                "afr_pct": afr_pct(f, dd),
                "ci_low_pct": low,
                "ci_high_pct": high,
                "rate_ratio_vs_fleet": round(afr_pct(f, dd) / fleet_afr, 4),
            }
        )
    rows.sort(key=lambda r: (-float(r["afr_pct"]), str(r["model"])))
    return {"items": rows[: int(args.get("limit", 20))], "method": "exact_poisson_95"}


def _fleet_summary(args: dict[str, Any]) -> Any:
    totals = _totals(args)
    dd = sum(v[0] for v in totals.values())
    f = sum(v[1] for v in totals.values())
    low, high = _approx_ci(f, dd)
    return {
        "source": args["source"],
        "drives": sum(FIXTURE_DRIVES.values()),
        "drive_days": dd,
        "failures": f,
        "afr_pct": afr_pct(f, dd),
        "ci_low_pct": low,
        "ci_high_pct": high,
        "method": "exact_poisson_95",
    }


def _list_models(args: dict[str, Any]) -> Any:
    return {
        "items": [
            {"model": m, "media": "hdd", "capacity_bytes": None, "drive_count": n}
            for m, n in FIXTURE_DRIVES.items()
            if n >= int(args.get("min_drives", 0))
        ]
    }


def _smart_trend(args: dict[str, Any]) -> Any:
    return {
        "model": args["model"],
        "attr": args["attr"],
        "series": [
            {"period": p, "p50": 0.0, "p95": 8.0, "nonzero_share": 0.061, "n_drives": 11}
            for p in _periods(args)
        ],
        "sample": "1% hash sample plus failed drives",
    }


def _failed_drives(args: dict[str, Any]) -> Any:
    return {
        "items": [
            {"drive_id": "ZJV0XXXX", "failed_on": "2026-05-02", "age_days": 1_412, "last_smart": {}}
        ],
        "page": 0,
        "size": 25,
        "total": 1,
    }


def _compare_rates(args: dict[str, Any]) -> Any:
    ka, dda = int(args["failures_a"]), int(args["drive_days_a"])
    kb, ddb = int(args["failures_b"]), int(args["drive_days_b"])
    ratio = (ka / dda) / (kb / ddb) if kb else None
    return {
        "rate_ratio": None if ratio is None else round(ratio, 4),
        "ci_low": 0.9,
        "ci_high": 21.5,
        "p_value": 0.0652,
        "method": "exact_conditional_binomial",
    }


def _afr_ci(args: dict[str, Any]) -> Any:
    f, dd = int(args["failures"]), int(args["drive_days"])
    low, high = _approx_ci(f, dd)
    return {"afr_pct": afr_pct(f, dd), "ci_low_pct": low, "ci_high_pct": high, "method": "x"}


def _change_point(args: dict[str, Any]) -> Any:
    series = args.get("series") or []
    period = series[len(series) // 2]["period"] if series else None
    return {"period": period, "statistic": 4.2, "p_value": 0.03, "method": "lrt_bootstrap_999"}


def _search(args: dict[str, Any]) -> Any:
    return {
        "items": [
            {
                "passage_id": "p_0001",
                "title": "Flash Reliability in Production",
                "url": "https://www.usenix.org/conference/fast16/technical-sessions/presentation/schroeder",
                "section": "5.2",
                "snippet": "Many drive failures are not preceded by any SMART error.",
                "score": 0.91,
            }
        ]
    }


def _get_passage(args: dict[str, Any]) -> Any:
    return {
        "passage_id": args["passage_id"],
        "title": "Flash Reliability in Production",
        "url": "https://www.usenix.org/conference/fast16/technical-sessions/presentation/schroeder",
        "section": "5.2",
        "text": "Many drive failures are not preceded by any SMART error.",
    }


DEFAULT_HANDLERS: dict[str, Handler] = {
    "fleet.list_models": _list_models,
    "fleet.cohort_afr": _cohort_afr,
    "fleet.compare_cohorts": _compare,
    "fleet.fleet_summary": _fleet_summary,
    "fleet.smart_trend": _smart_trend,
    "fleet.failed_drives": _failed_drives,
    "stats.afr_ci": _afr_ci,
    "stats.compare_rates": _compare_rates,
    "stats.change_point": _change_point,
    "docs.search": _search,
    "docs.get_passage": _get_passage,
}


class FakeToolGateway:
    """Serves `handlers[server.name](args)` wrapped in a contracts §5 envelope.

    A handler may return `data`, or a full envelope (a dict with `tool` and `data` keys), or raise
    `ToolCallError`. `calls` records every call for assertions.
    """

    def __init__(
        self,
        handlers: Mapping[str, Handler] | None = None,
        specs: tuple[ToolSpec, ...] | list[ToolSpec] | None = None,
        *,
        servers: tuple[str, ...] = ("fleet", "stats", "docs"),
    ) -> None:
        self._handlers = dict(DEFAULT_HANDLERS)
        self._handlers.update(handlers or {})
        self._specs = [s for s in (specs or DEFAULT_SPECS) if s.server in servers]
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    async def call(self, server: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((server, name, copy.deepcopy(args)))
        spec = next((s for s in self._specs if s.server == server and s.name == name), None)
        handler = self._handlers.get(f"{server}.{name}")
        if spec is None or handler is None:
            raise ToolCallError("not_found", f"unknown tool {server}.{name}")
        missing = [k for k in spec.input_schema.get("required", []) if k not in args]
        if missing:
            raise ToolCallError("invalid_argument", f"missing required argument(s): {missing}")
        unknown = [k for k in args if k not in spec.input_schema.get("properties", {})]
        if unknown:
            raise ToolCallError("invalid_argument", f"unknown argument(s): {unknown}")
        result = handler(dict(args))
        if isinstance(result, dict) and "tool" in result and "data" in result:
            return copy.deepcopy(result)
        return {
            "evidence_id": "",
            "tool": f"{server}.{name}",
            "args": copy.deepcopy(args),
            "source": f"fake {server}",
            "generated_at": datetime.now(UTC).isoformat(),
            "data": result,
            "truncated": False,
            "next_page": None,
        }

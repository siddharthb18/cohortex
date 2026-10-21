"""Eval runner (FR-EVAL-2): drives agent-service over HTTP with bounded concurrency.

Protocol (contracts §4, implementation-notes §7): ``POST /v1/investigations`` returns 202 with an
ID; the runner polls ``GET /v1/investigations/{id}`` until the status is terminal, then fetches the
evidence cited by summary claims (``GET /v1/investigations/{id}/evidence/{eid}``) for the M4
independent recheck.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from cohortex_evals.cases import GoldenCase
from cohortex_evals.records import CaseRun
from cohortex_evals.report_model import Investigation, parse_report

Mode = Literal["single", "orchestrated"]
RETRY_STATUSES = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class RunConfig:
    mode: Mode = "single"
    concurrency: int = 2  # the free LLM tier is rate-limited (ADR-013)
    case_timeout_s: float = 240.0  # agent budget is 180 s (COHORTEX_MAX_SECONDS) plus slack
    poll_interval_s: float = 2.0
    send_scope: bool = True
    max_retries: int = 4
    retry_backoff_s: float = 2.0


class AgentServiceError(Exception):
    pass


class AgentClient:
    """Thin async client for the agent-service investigation API."""

    def __init__(self, http: httpx.AsyncClient, config: RunConfig) -> None:
        self._http = http
        self._config = config

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            response = await self._http.request(method, url, **kwargs)
            if response.status_code not in RETRY_STATUSES or attempt >= self._config.max_retries:
                return response
            attempt += 1
            retry_after = response.headers.get("retry-after", "")
            delay = (
                float(retry_after)
                if retry_after.replace(".", "", 1).isdigit()
                else self._config.retry_backoff_s * 2 ** (attempt - 1)
            )
            await asyncio.sleep(delay)

    async def create(self, case: GoldenCase) -> str:
        body: dict[str, Any] = {"question": case.question, "mode": self._config.mode}
        if self._config.send_scope and case.scope is not None:
            body["scope"] = case.scope.model_dump(mode="json", exclude_none=True)
        response = await self._request("POST", "/v1/investigations", json=body)
        if response.status_code not in (200, 201, 202):
            raise AgentServiceError(
                f"POST /v1/investigations -> {response.status_code}: {response.text[:300]}"
            )
        investigation_id = response.json().get("id")
        if not isinstance(investigation_id, str) or not investigation_id:
            raise AgentServiceError("POST /v1/investigations returned no id")
        return investigation_id

    async def get(self, investigation_id: str) -> Investigation:
        response = await self._request("GET", f"/v1/investigations/{investigation_id}")
        if response.status_code != 200:
            raise AgentServiceError(
                f"GET /v1/investigations/{investigation_id} -> {response.status_code}"
            )
        return Investigation.model_validate(response.json())

    async def wait(self, investigation_id: str) -> Investigation:
        while True:
            inv = await self.get(investigation_id)
            if inv.terminal:
                return inv
            await asyncio.sleep(self._config.poll_interval_s)

    async def evidence(self, investigation_id: str, evidence_id: str) -> dict[str, Any]:
        response = await self._request(
            "GET", f"/v1/investigations/{investigation_id}/evidence/{evidence_id}"
        )
        if response.status_code != 200:
            raise AgentServiceError(f"evidence {evidence_id} -> {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise AgentServiceError(f"evidence {evidence_id}: body is not an object")
        return body


def summary_evidence_ids(report_raw: dict[str, Any] | None) -> list[str]:
    report = parse_report(report_raw)
    if report is None:
        return []
    ids: list[str] = []
    for claim in report.summary:
        for eid in [*claim.evidence_ids, *(n.evidence_id for n in claim.numbers)]:
            if eid and eid not in ids:
                ids.append(eid)
    return ids


async def run_case(client: AgentClient, case: GoldenCase, config: RunConfig) -> CaseRun:
    start = time.monotonic()
    investigation_id: str | None = None
    try:
        async with asyncio.timeout(config.case_timeout_s):
            investigation_id = await client.create(case)
            inv = await client.wait(investigation_id)
            latency = time.monotonic() - start
            evidence: dict[str, dict[str, Any]] = {}
            evidence_errors: dict[str, str] = {}
            for eid in summary_evidence_ids(inv.report):
                try:
                    evidence[eid] = await client.evidence(investigation_id, eid)
                except AgentServiceError as exc:
                    evidence_errors[eid] = str(exc)
    except TimeoutError:
        return CaseRun(
            case_id=case.id,
            investigation_id=investigation_id,
            status="timeout",
            error=f"no terminal status within {config.case_timeout_s:g} s",
            latency_s=time.monotonic() - start,
        )
    except (AgentServiceError, httpx.HTTPError, ValueError) as exc:
        return CaseRun(
            case_id=case.id,
            investigation_id=investigation_id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            latency_s=time.monotonic() - start,
        )
    return CaseRun(
        case_id=case.id,
        investigation_id=investigation_id,
        status=inv.status,
        latency_s=latency,
        tokens_in=inv.tokens_in,
        tokens_out=inv.tokens_out,
        cost_usd=inv.cost_usd,
        llm_model=inv.llm_model,
        report=inv.report,
        markdown=inv.markdown,
        evidence=evidence,
        evidence_errors=evidence_errors,
    )


async def run_cases(
    cases: Sequence[GoldenCase],
    base_url: str,
    config: RunConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    on_done: Callable[[CaseRun], None] | None = None,
) -> list[CaseRun]:
    """Run every case, at most ``config.concurrency`` at a time; results keep case order."""
    if config.concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    semaphore = asyncio.Semaphore(config.concurrency)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout) as http:
        client = AgentClient(http, config)

        async def bounded(case: GoldenCase) -> CaseRun:
            async with semaphore:
                result = await run_case(client, case, config)
            if on_done is not None:
                on_done(result)
            return result

        return list(await asyncio.gather(*(bounded(c) for c in cases)))

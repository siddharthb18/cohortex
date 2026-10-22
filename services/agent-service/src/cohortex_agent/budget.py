"""Per-investigation budget guards (FR-AGT-8, ERS §5).

- Tool calls: the call that would exceed `max_tool_calls` is not executed. Gathering stops, the
  drafter still writes from the evidence already collected, and the run ends `budget_exceeded`.
- Input tokens: checked before every LLM call; at or over the limit the run stops at once.
- Wall time: checked before every LLM call and enforced by an asyncio timeout around the graph.
A stop saves a partial report built from whatever was already checked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from cohortex_agent.llm.base import Usage


class BudgetExceeded(Exception):  # noqa: N818 - domain name used in specs
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Budget:
    max_tool_calls: int
    max_input_tokens: int
    max_seconds: float
    started: float = field(default_factory=time.monotonic)
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_limit_hit: bool = False
    stop_reason: str | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def check_llm(self) -> None:
        """Raise `BudgetExceeded` if another LLM call is not allowed."""
        if self.input_tokens >= self.max_input_tokens:
            self.stop_reason = (
                f"input-token budget reached ({self.input_tokens} of {self.max_input_tokens})"
            )
            raise BudgetExceeded(self.stop_reason)
        if self.elapsed() >= self.max_seconds:
            self.stop_reason = f"wall-time budget reached ({self.max_seconds:g} s)"
            raise BudgetExceeded(self.stop_reason)

    def try_reserve_tool_call(self) -> bool:
        """Count one tool call; False (and `tool_limit_hit`) when the limit is already used up."""
        if self.tool_calls >= self.max_tool_calls:
            self.tool_limit_hit = True
            return False
        self.tool_calls += 1
        return True

    def add_usage(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens

    def limitation(self) -> str | None:
        if self.stop_reason:
            return f"Budget exceeded: {self.stop_reason}; this is a partial report."
        if self.tool_limit_hit:
            return (
                f"Budget exceeded: tool-call budget reached ({self.max_tool_calls} calls); "
                "the report uses only the evidence gathered before the limit."
            )
        return None

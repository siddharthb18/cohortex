"""Faithfulness judge interface (M5, FR-EVAL-5, Phase 3). Deliberately not implemented.

The judge asks one binary question per atomic claim: "Is this claim fully supported by the cited
evidence text?" It never sees the agent's reasoning (evaluation spec §3).

It may count toward M5 only after validation, which is human-owned:

1. Siddharth labels at least 60 atomic claims by hand, balanced supported/unsupported.
2. 20 are used for prompt development, 40 are held out.
3. On the held-out 40 the judge needs true-positive and true-negative rates both >= 0.80.
4. The validation report lives in ``evals/judge/validation.md``; re-validate whenever the judge
   prompt or judge model (``JUDGE_MODEL``) changes.

Until then, :class:`UnvalidatedJudge` is the only implementation and M5 is reported as ``n/a``.
Tests never call a live LLM; a real judge must be exercised through ``evals/recordings/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class JudgeVerdict:
    claim_text: str
    supported: bool
    rationale: str = ""


class FaithfulnessJudge(Protocol):
    """Binary support judgment for one atomic claim against its cited evidence text."""

    def judge(self, claim_text: str, evidence_text: str) -> JudgeVerdict: ...


class JudgeNotValidatedError(NotImplementedError):
    """Raised until the judge passes human validation (WP-16)."""


class UnvalidatedJudge:
    """Placeholder: refuses to judge so nothing can silently count toward M5."""

    def judge(self, claim_text: str, evidence_text: str) -> JudgeVerdict:
        raise JudgeNotValidatedError(
            "The faithfulness judge is Phase 3 (WP-16) and must be validated against "
            "Siddharth's 60 hand labels before it counts; see evals/harness/README.md."
        )

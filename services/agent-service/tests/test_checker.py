"""Evidence checker rules (ADR-008, FR-AGT-6, FR-AGT-7) at unit level."""

from __future__ import annotations

from typing import Any

import pytest
from cohortex_agent.checker import (
    PathError,
    check_claim,
    check_draft,
    extract_text_numbers,
    infer_unit,
    resolve_path,
    values_match,
)
from cohortex_agent.schemas import Claim, DraftOutput, NumberRef

EVIDENCE: dict[str, dict[str, Any]] = {
    "ev_afr": {
        "tool": "fleet.cohort_afr",
        "args": {"source": "backblaze"},
        "data": {
            "series": [
                {"period": "2026Q1", "drive_days": 98010, "failures": 2, "afr_pct": 0.7448},
                {"period": "2026Q2", "drive_days": 98189, "failures": 9, "afr_pct": 3.3456},
            ]
        },
    },
    "ev_cmp": {
        "tool": "fleet.compare_cohorts",
        "data": {"items": [{"model": "A", "rate_ratio_vs_fleet": 1.82, "drive_count": 40}]},
    },
    "ev_list": {"tool": "fleet.list_models", "data": [{"model": "A", "drive_count": 1079}]},
    "ev_rates": {"tool": "stats.compare_rates", "data": {"rate_ratio": 4.4918, "p_value": 0.0652}},
    "ev_failed": {"tool": "fleet.failed_drives", "data": {"items": [{"age_days": 1412}]}},
    "ev_docs": {
        "tool": "docs.search",
        "data": {"items": [{"passage_id": "p_0001", "url": "https://example.org/paper"}]},
    },
    "ev_error": {"tool": "fleet.cohort_afr", "error": {"code": "not_found", "message": "x"}},
}


def num(value: float, unit: str, evidence_id: str, field: str) -> NumberRef:
    return NumberRef(value=value, unit=unit, evidence_id=evidence_id, field=field)  # type: ignore[arg-type]


def check(claim: Claim) -> list[str]:
    return check_claim(claim, EVIDENCE, {"p_0001"}).notes


@pytest.mark.parametrize(
    ("field", "unit"),
    [
        ("series[0].afr_pct", "pct"),
        ("ci_low_pct", "pct"),
        ("items[2].failures", "count"),
        ("drive_count", "count"),
        ("[0].n_drives", "count"),
        ("drives", "count"),
        ("series[1].drive_days", "drive_days"),
        ("items[0].age_days", "days"),
        ("items[0].rate_ratio_vs_fleet", "ratio"),
        ("rate_ratio", "ratio"),
        ("p_value", "p_value"),
        ("statistic", "raw"),
        ("ci_low", "ratio"),
    ],
)
def test_unit_is_inferred_from_the_field_name(field: str, unit: str) -> None:
    assert infer_unit(field) == unit


def test_resolve_path_reads_nested_fields_and_lists() -> None:
    data = EVIDENCE["ev_afr"]["data"]
    assert resolve_path(data, "series[1].afr_pct") == 3.3456
    assert resolve_path(data, "data.series[0].failures") == 2
    assert resolve_path(EVIDENCE["ev_list"]["data"], "[0].drive_count") == 1079
    for bad in ("series[5].afr_pct", "series.afr_pct", "nope", "series[0]..x", ""):
        with pytest.raises(PathError):
            resolve_path(data, bad)


def test_tolerance_is_relative_or_absolute_for_rates_and_exact_for_counts() -> None:
    assert values_match("pct", 3.35, 3.3456)  # within 0.01 absolute
    assert values_match("pct", 1000.0, 1004.0)  # within 0.5% relative
    assert not values_match("pct", 3.4, 3.3456)
    assert values_match("p_value", 0.0652, 0.0652)
    assert values_match("count", 9, 9)
    assert not values_match("count", 9.0001, 9)
    assert not values_match("drive_days", 98190, 98189)
    assert not values_match("days", 1411, 1412)


def test_a_correct_claim_is_supported_and_its_evidence_cited() -> None:
    claim = Claim(
        text="AFR rose to 3.35% in Q2 2026 from 0.74% with 9 failures over 98,189 drive-days.",
        numbers=[
            num(3.3456, "pct", "ev_afr", "series[1].afr_pct"),
            num(0.7448, "pct", "ev_afr", "series[0].afr_pct"),
            num(9, "count", "ev_afr", "series[1].failures"),
            num(98189, "drive_days", "ev_afr", "series[1].drive_days"),
        ],
    )
    result = check_claim(claim, EVIDENCE, set())
    assert result.notes == []
    assert result.claim.status == "supported"
    assert result.claim.evidence_ids == ["ev_afr"]


def test_fabricated_number_in_number_ref_is_caught() -> None:  # FR-AGT-6
    claim = Claim(
        text="Q2 2026 had 12 failures.",
        numbers=[num(12, "count", "ev_afr", "series[1].failures")],
        evidence_ids=["ev_afr"],
    )
    notes = check(claim)
    assert len(notes) == 1
    assert "evidence value is 9" in notes[0]


def test_fabricated_number_only_in_text_is_caught() -> None:  # FR-AGT-6
    claim = Claim(text="The fleet AFR was 5.1% in Q2 2026.", evidence_ids=["ev_afr"])
    assert check(claim) == ["number '5.1' in the text is not backed by a NumberRef"]


def test_unit_mismatch_unknown_evidence_failed_call_and_bad_path_are_caught() -> None:
    assert (
        "unit pct does not match field unit count"
        in check(
            Claim(text="9 failures.", numbers=[num(9, "pct", "ev_afr", "series[1].failures")])
        )[0]
    )
    assert (
        "unknown evidence_id"
        in check(
            Claim(text="9 failures.", numbers=[num(9, "count", "ev_nope", "series[1].failures")])
        )[0]
    )
    assert (
        "failed tool call"
        in check(Claim(text="9 failures.", numbers=[num(9, "count", "ev_error", "failures")]))[0]
    )
    assert (
        "field not found"
        in check(
            Claim(text="9 failures.", numbers=[num(9, "count", "ev_afr", "series[9].failures")])
        )[0]
    )


def test_claims_without_any_source_are_unsupported() -> None:  # FR-AGT-7
    assert check(Claim(text="Seagate drives are unreliable.")) == ["cites no evidence or passage"]
    assert check(Claim(text="Cited", evidence_ids=["ev_missing"])) == [
        "cites unknown evidence_id ev_missing"
    ]
    assert check(Claim(text="Literature says so.", passage_ids=["p_0001"])) == []
    assert check(Claim(text="Literature says so.", passage_ids=["p_9999"])) == [
        "cites unknown passage_id p_9999"
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ST12000NM000J in Q2 2026 (2026-04-01 to 2026-06-30)", []),
        ("AFR 3.35% (95% CI 1.53" + chr(0x2013) + "6.36)", ["3.35", "1.53", "6.36"]),
        ("p<0.05 and p = 0.065 and n=12", ["0.05", "0.065", "12"]),
        ("rate ratio 4.5x over 98,189 drive-days", ["4.5", "98,189"]),
        ("SMART 187 rose; top 3 models; Alibaba 2018-2019", []),
        ("not significant at 0.05", []),
    ],
)
def test_text_number_extraction_skips_labels(text: str, expected: list[str]) -> None:
    assert [n.raw for n in extract_text_numbers(text)] == expected


def test_comparators_in_text_are_checked_against_cited_values() -> None:
    supported = Claim(
        text="The difference is significant (p < 0.1).",
        numbers=[num(0.0652, "p_value", "ev_rates", "p_value")],
    )
    assert check(supported) == []
    overstated = Claim(
        text="The difference is significant (p < 0.01).",
        numbers=[num(0.0652, "p_value", "ev_rates", "p_value")],
    )
    assert check(overstated) == ["number '0.01' in the text is not backed by a NumberRef"]


def test_check_draft_marks_every_claim_including_hypothesis_support() -> None:
    good = Claim(
        text="Ratio 1.82.", numbers=[num(1.82, "ratio", "ev_cmp", "items[0].rate_ratio_vs_fleet")]
    )
    bad = Claim(
        text="Ratio 2.5.", numbers=[num(2.5, "ratio", "ev_cmp", "items[0].rate_ratio_vs_fleet")]
    )
    draft = DraftOutput.model_validate(
        {
            "summary": [good.model_dump()],
            "findings": [good.model_dump(), bad.model_dump()],
            "hypotheses": [
                {
                    "statement": "s",
                    "support": [bad.model_dump()],
                    "confidence": "low",
                    "how_to_confirm": "x",
                }
            ],
        }
    )
    result = check_draft(draft, EVIDENCE)
    assert result.supported == 2
    assert len(result.unsupported) == 2
    assert result.draft.findings[1].status == "unsupported"
    assert result.draft.hypotheses[0].support[0].status == "unsupported"
    assert all("2.5" in note for note in result.notes())


def test_drafter_output_is_truncated_not_rejected() -> None:
    claim = {"text": "t", "evidence_ids": ["e"]}
    draft = DraftOutput.model_validate(
        {"summary": [claim] * 7, "recommended_actions": ["a"] * 9, "findings": []}
    )
    assert len(draft.summary) == 5
    assert len(draft.recommended_actions) == 5


def test_numbers_given_as_tool_inputs_need_no_number_ref() -> None:
    evidence = {
        "ev_cmp60": {
            "tool": "fleet.compare_cohorts",
            "args": {"source": "backblaze", "min_drives": 60},
            "data": {"items": [{"model": "A", "afr_pct": 9.7512}]},
        }
    }
    ref = NumberRef(value=9.7512, unit="pct", evidence_id="ev_cmp60", field="items[0].afr_pct")
    text = "Among models with at least 60 drives, A had the highest AFR at 9.75%."
    supported = check_claim(
        Claim(text=text, numbers=[ref], evidence_ids=["ev_cmp60"]), evidence, set()
    )
    assert supported.claim.status == "supported", supported.notes
    invented = Claim(text="A had 61 failures.", numbers=[], evidence_ids=["ev_cmp60"])
    assert check_claim(invented, evidence, set()).claim.status == "unsupported"


@pytest.mark.parametrize(
    "text",
    [
        "p = 1.07923 \u00d7 10\u207b\u00b9\u2070",
        "p = 1.07923 x 10^-10",
        "p = 1.07923\u00d710\u207b\u00b9\u2070.",
        "p = 1.07923e-10",
    ],
)
def test_scientific_notation_is_one_number(text: str) -> None:
    (number,) = extract_text_numbers(text)
    assert number.value == pytest.approx(1.07923e-10)

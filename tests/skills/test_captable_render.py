"""Deterministic Markdown rendering, replacing the removed HTML output."""
from copy import deepcopy
from datetime import date
from lib.captable.render_markdown import render_report
from lib.captable.rubric import apply_rubric
from skills.captable.captable import build_scenarios

def _snapshot() -> dict:
    return {
        "dataset": "fixture-robotics",
        "as_of_date": "2026-06-30",
        "generated_at": "2026-09-05T12:00:00+00:00",
        "tool_version": "captable_build/0.3",
        "sources": [
            {"doc": "captable.md", "class": "captable_current",
             "date": "2026-06-30"},
            {"doc": "cla.md", "class": "cla_executed", "date": None},
        ],
        "share_classes": [
            {"id": "common", "name": "Common", "nominal_value": 0.10,
             "votes_per_share": 1},
        ],
        "stakeholders": [
            {"name": "Petra Muster", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 600_000}],
             "diluted_count": 600_000},
            {"name": "Angel <script>alert(1)</script>", "kind": "entity",
             "role": "investor", "group": "Syndicate A",
             "holdings": [{"class_id": "common", "count": 300_000}],
             "diluted_count": 300_000},
            {"name": "Treasury", "kind": "treasury", "role": "company",
             "holdings": [{"class_id": "common", "count": 50_000}],
             "diluted_count": None},
            {"name": "ESOP", "kind": "pool", "role": "employee",
             "holdings": [], "diluted_count": 100_000},
        ],
        "pools": [
            {"kind": "esop", "label": "ESOP 2025", "total": 100_000,
             "granted": 40_000, "unallocated": 60_000},
        ],
        "totals": {
            "by_class": [{"class_id": "common", "issued_total": 950_000}],
            "diluted_total": 1_000_000,
        },
        "fully_diluted_definition": {"value": "full_pools"},
        "convertibles": [
            {"document": "cla.md", "status": "executed",
             "principal_total": {"value": 250_000},
             "currency": {"value": "CHF"},
             "interest_rate_pct": {"value": 5},
             "maturity_date": {"value": "2025-12-31"},
             "discount_pct": {"value": 20},
             "valuation_cap": {"value": 8_000_000},
             "lenders": [{"name": {"value": "Petra Muster"}}]},
        ],
        "aggregation": {
            "outstanding_principal_total": 250_000.0,
            "outstanding_unknown_amounts": 0,
            "ten_twenty_rule": {
                "max_lenders_on_identical_terms": 1,
                "total_lenders_all_terms": 1,
                "ten_rule": "within", "twenty_rule": "within",
            },
            "maturity": [
                {"document": "cla.md", "maturity_date": "2025-12-31",
                 "status": "expired_check_for_conversion",
                 "detail": "Maturity passed."},
            ],
            "esignature": [
                {"document": "cla.md", "signatures_complete_claimed": True,
                 "esign_markers": None, "corroborated": "not_applicable"},
            ],
        },
        "assessment": [{"document": "cla.md", "worst_severity": "medium"}],
        "validation": [
            {"check": "issued_totals", "status": "pass",
             "severity": "info", "detail": "All classes add up."},
            {"check": "shrinking_holder", "status": "warn",
             "severity": "medium", "detail": "Bruno 300k -> 250k."},
        ],
        "diligence_questions": ["Ask about the bridge."],
        "assumptions": ["as_of derived from the document header."],
    }


def _computed(data):
    result = build_scenarios(data, valuation_date=date(2026, 9, 8))
    result["rubric"] = apply_rubric(data)
    result["rubric_scope_note"] = "Source-date rubric; scenarios are hypothetical."
    return result


def test_markdown_copies_scenario_numbers_without_llm_tables():
    data = _snapshot()
    computed = _computed(data)
    output = render_report(data, computed, "Discuss the implications.")
    for scenario in computed["scenarios"]:
        assert str(scenario["price_per_share"]) in output
        assert str(scenario["founders_post_round_pct"]) in output
        for loan, price in scenario["note_conversion_prices"].items():
            assert str(price) in output
    assert "## Commentary\n\nDiscuss the implications." in output
    assert "<html" not in output


def test_markdown_is_deterministic_and_preserves_inputs():
    data = _snapshot()
    computed = _computed(data)
    before = deepcopy((data, computed))
    assert render_report(data, computed, "Notes") == render_report(data, computed, "Notes")
    assert (data, computed) == before


def test_markdown_discloses_missing_fx_instead_of_hiding_scenarios():
    data = _snapshot()
    computed = _computed(data)
    computed["scenarios"] = []
    computed["scenario_flags"] = [{"item": "mixed_currencies", "status": "flag", "severity": "high", "detail": "USD loan has no FX rate."}]
    assert "USD loan has no FX rate." in render_report(data, computed, "Notes")


def test_markdown_preserves_literal_source_text_and_maturity_findings():
    data = _snapshot()
    data["stakeholders"][0]["name"] = "Name | with separator"
    output = render_report(data, _computed(data), "Notes")
    assert "<script>" not in output
    assert "&lt;script&gt;" in output
    assert "Name \\| with separator" in output
    assert "expired_check_for_conversion" in output
    assert "not_applicable" in output

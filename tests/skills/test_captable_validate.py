"""Tests for stage 5 reviewer, stage 6 validation, and stage 7 assembly."""

from __future__ import annotations

from lib.captable.snapshot import render_markdown, resolve_as_of
from lib.captable.table_extraction import _review_captable
from lib.captable.validate import (
    check_cross_snapshot,
    check_diluted_equation,
    check_issued_totals,
    check_nominal_floor,
    check_pool_consistency,
    check_register_reconciliation,
)


def _captable_realistic() -> dict:
    """Compressed real-world cap-table shape (anonymized) with genuine totals arithmetic."""
    return {
        "document": "cap.xlsx",
        "share_classes": [
            {"id": "common", "name": "Common", "nominal_value": 0.01,
             "votes_per_share": 1},
            {"id": "preferred_seed", "name": "Preferred Seed",
             "nominal_value": 0.01, "votes_per_share": 1},
        ],
        "stakeholders": [
            {"name": "Founder A", "group": "Founders", "kind": "individual",
             "role": "founder",
             "holdings": [{"class_id": "common", "count": 8_039_373}],
             "diluted_count": 8_039_373, "invested_amount": 0},
            {"name": "Option Holder", "group": "Founders",
             "kind": "individual", "role": "founder", "holdings": [],
             "diluted_count": 1_845_607, "invested_amount": 0},
            {"name": "VC One", "group": "VC Investors", "kind": "entity",
             "role": "investor",
             "holdings": [{"class_id": "preferred_seed",
                           "count": 10_570_088}],
             "diluted_count": 10_570_088, "invested_amount": 17_000_000},
            {"name": "Employees", "group": "Employees", "kind": "individual",
             "role": "employee",
             "holdings": [{"class_id": "common", "count": 612_529}],
             "diluted_count": 1_749_942, "invested_amount": 0},
            {"name": "Authorized Capital", "group": "Equity plans grantable",
             "kind": "authorized_capital", "role": "pool", "holdings": [],
             "diluted_count": 865_149, "invested_amount": 0},
            {"name": "Treasury", "group": "Company", "kind": "treasury",
             "role": "company",
             "holdings": [{"class_id": "common", "count": 1_348_098}],
             "diluted_count": None, "invested_amount": 0},
        ],
        "pools": [
            {"kind": "grantable", "label": "Equity plans grantable",
             "total": 865_149, "granted": None, "unallocated": 865_149},
        ],
        "totals": {
            "by_class": [
                {"class_id": "common", "issued_total": 10_000_000},
                {"class_id": "preferred_seed", "issued_total": 10_570_088},
            ],
            "diluted_total": 23_070_088,
            "quote": "Total | 23070088 | 10000000 | 10570088",
        },
        "fully_diluted_definition": {"value": "full_pools", "quote": None},
        "assumptions": [],
    }


def test_issued_totals_pass_on_consistent_table() -> None:
    findings = check_issued_totals(_captable_realistic())
    assert all(f["status"] == "pass" for f in findings)


def test_issued_totals_fail_on_dropped_rows() -> None:
    captable = _captable_realistic()
    captable["stakeholders"] = captable["stakeholders"][:2]
    findings = check_issued_totals(captable)
    assert any(f["status"] == "fail" for f in findings)


def test_diluted_equation_holds_on_real_arithmetic() -> None:
    """diluted = issued - treasury + option/pool deltas (real-world numbers, anonymized)."""
    finding = check_diluted_equation(_captable_realistic())[0]
    assert finding["status"] == "pass", finding["detail"]


def test_diluted_equation_fails_when_treasury_counted_as_diluting() -> None:
    captable = _captable_realistic()
    for s in captable["stakeholders"]:
        if s["kind"] == "treasury":
            s["kind"] = "entity"  # mis-modeled: treasury treated as holder
            s["diluted_count"] = 1_348_098
    finding = check_diluted_equation(captable)[0]
    assert finding["status"] == "fail"


def test_register_reconciliation_flags_mismatch() -> None:
    register = {
        "entries": [
            {"name": "Founder A", "current_common": 8_039_373,
             "current_preferred": None, "current_participation_pct": 39.1,
             "first_acquisition_date": "2019-04-11",
             "last_change_date": None},
            {"name": "VC One", "current_common": None,
             "current_preferred": 9_000_000,
             "current_participation_pct": 44.0,
             "first_acquisition_date": "2023-01-15",
             "last_change_date": None},
        ]
    }
    findings = check_register_reconciliation(
        _captable_realistic(), register
    )
    assert any(
        f["check"] == "register_mismatch" and "VC One" in f["detail"]
        for f in findings
    )
    assert not any(
        f["check"] == "register_mismatch" and "Founder A" in f["detail"]
        for f in findings
    )


def test_pool_consistency_flags_disagreeing_sources() -> None:
    pool_doc = {
        "document": "pool.xlsx",
        "pools": [{"kind": "esop", "label": "ESOP", "total": 1_000_000,
                   "granted": None, "unallocated": None}],
    }
    finding = check_pool_consistency(_captable_realistic(), [pool_doc])[0]
    assert finding["status"] == "fail"
    assert "865" in finding["detail"].replace(",", "")


def test_nominal_floor_fires_below_nominal() -> None:
    cla = {
        "document": "cla.pdf",
        "valuation_cap": {"value": 100_000, "quote": "q"},
    }
    findings = check_nominal_floor(_captable_realistic(), [cla])
    assert findings and findings[0]["severity"] == "severe"


def test_cross_snapshot_flags_shrinking_class_and_holder() -> None:
    previous = _captable_realistic()
    current = _captable_realistic()
    current["totals"]["by_class"][0]["issued_total"] = 9_000_000
    current["stakeholders"][0]["holdings"][0]["count"] = 7_000_000
    findings = check_cross_snapshot(previous, current)
    checks = {f["check"] for f in findings}
    assert "shrinking_share_class" in checks
    assert "shrinking_holder" in checks


def test_captable_reviewer_rejects_dropped_rows() -> None:
    reviewer = _review_captable("Total | 23070088 | 10000000 | 10570088")
    output = _captable_realistic()
    output["stakeholders"] = output["stakeholders"][:2]
    assert any(
        "missing or double-counted" in p for p in reviewer(output).problems
    )
    assert not reviewer(_captable_realistic()).problems


def test_resolve_as_of_prefers_stated_then_classified() -> None:
    classification = {
        "documents": [
            {"filename": "cap.xlsx", "as_of_date": "2026-03"},
            {"filename": "reg.pdf", "as_of_date": "2026-03"},
        ]
    }
    stated, notes = resolve_as_of(
        {"as_of_date": {"value": "2026-04-30"}}, classification, ["cap.xlsx"]
    )
    assert stated == "2026-04-30" and not notes
    derived, notes = resolve_as_of(
        {"as_of_date": {"value": None}}, classification, ["cap.xlsx"]
    )
    assert derived == "2026-03" and notes


def test_render_markdown_contains_tables_not_prose() -> None:
    snapshot = {
        "dataset": "x", "as_of_date": "2026-03",
        "generated_at": "2026-09-04T10:00:00+00:00",
        "tool_version": "t", "stakeholders": [], "totals": {},
        "convertibles": [], "aggregation": {}, "assessment": [],
        "validation": [], "diligence_questions": ["q1"], "assumptions": [],
    }
    md = render_markdown(snapshot)
    assert "## Ownership" in md and "- q1" in md


def test_names_match_handles_middle_names() -> None:
    from lib.captable.aggregation import names_match

    assert names_match("Anna Beispiel", "Anna Barbara Beispiel")
    assert names_match("Anna Barbara-Beispiel", "Anna Barbara Beispiel")
    assert not names_match("Anna Beispiel", "Timo Beispiel")
    assert not names_match("Ali", "Anna Beispiel")  # single token too weak

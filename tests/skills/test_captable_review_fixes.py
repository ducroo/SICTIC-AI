"""Regression tests for the 2026-09-04 code-review findings."""

from __future__ import annotations

from datetime import date

import pytest

from lib.captable.aggregation import _loan_amounts, aggregate_clas
from lib.captable.assessment import assess_cla
from lib.captable.rubric import apply_rubric
from lib.captable.validate import (
    check_cla_lifecycle,
    check_cross_snapshot,
    check_register_reconciliation,
)
from tests.skills.test_captable_assessment import RULES, _cla, _q


def test_multilender_total_apportioned_not_zero() -> None:
    """Finding 1: unstated per-lender amounts must not vanish."""
    cla = _cla(
        lenders=[
            {"name": "A", "kind": "entity", "domicile": "CH",
             "principal_amount": None, "quote": "q"},
            {"name": "B", "kind": "entity", "domicile": "other",
             "principal_amount": None, "quote": "q"},
            {"name": "C", "kind": "entity", "domicile": "other",
             "principal_amount": None, "quote": "q"},
        ],
        principal_total=_q(900_000),
    )
    amounts = dict(_loan_amounts(cla))
    assert sum(amounts.values()) == pytest.approx(900_000)
    result = aggregate_clas([cla], run_date=date(2026, 1, 1))
    assert result["outstanding_principal_total"] == pytest.approx(900_000)
    assert any("apportioned equally" in q for q in result["diligence_questions"])


def test_partial_lender_amounts_fill_remainder() -> None:
    cla = _cla(
        lenders=[
            {"name": "A", "kind": "entity", "domicile": "CH",
             "principal_amount": 500_000, "quote": "q"},
            {"name": "B", "kind": "entity", "domicile": "CH",
             "principal_amount": None, "quote": "q"},
        ],
        principal_total=_q(900_000),
    )
    amounts = dict(_loan_amounts(cla))
    assert amounts["B"] == pytest.approx(400_000)


def test_rubric_zero_founders_flags_not_ok() -> None:
    """Finding 4: 0% founders is the worst case, not 'ok'."""
    snapshot = {
        "stakeholders": [
            {"name": "VC", "kind": "entity", "role": "investor",
             "holdings": [{"class_id": "common", "count": 950_000}],
             "diluted_count": 950_000},
            {"name": "Emp", "kind": "individual", "role": "employee",
             "holdings": [{"class_id": "common", "count": 50_000}],
             "diluted_count": 50_000},
        ],
        "fully_diluted_definition": {"value": "full_pools"},
    }
    findings = {f["item"]: f for f in apply_rubric(snapshot)}
    assert findings["founder_majority"]["status"] == "flag"
    assert findings["investor_dominance"]["status"] == "flag"


def test_lifecycle_compares_parsed_dates_across_formats() -> None:
    """Finding 8: '15.03.2024' acquired vs '2024-01-10' executed must warn."""
    captable = {
        "stakeholders": [
            {"name": "Lena Lender", "kind": "individual",
             "role": "investor",
             "holdings": [{"class_id": "common", "count": 100}]}
        ]
    }
    register = {
        "entries": [
            {"name": "Lena Lender", "current_common": 100,
             "current_preferred": None, "current_participation_pct": 1,
             "first_acquisition_date": "15.03.2024",
             "last_change_date": None}
        ]
    }
    cla = _cla(
        lenders=[{"name": "Lena Lender", "kind": "individual",
                  "domicile": "CH", "principal_amount": 10_000,
                  "quote": "q"}],
        execution_date=_q("2024-01-10"),
    )
    findings = check_cla_lifecycle(captable, register, [cla])
    assert any(f["check"] == "cla_possibly_converted" for f in findings)


def test_register_unmappable_class_ids_compare_totals() -> None:
    """Finding 7: 'Stammaktien' ids must not spray false mismatches."""
    captable = {
        "stakeholders": [
            {"name": "Anna", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "stammaktien", "count": 1000}]}
        ]
    }
    register = {
        "entries": [
            {"name": "Anna", "current_common": 1000,
             "current_preferred": None, "current_participation_pct": 100,
             "first_acquisition_date": None, "last_change_date": None}
        ]
    }
    findings = check_register_reconciliation(captable, register)
    rollup = next(
        f for f in findings if f["check"] == "register_reconciliation"
    )
    assert rollup["status"] == "pass"


def test_term_sheet_supersession_uses_fuzzy_names() -> None:
    """Finding 9: middle names must not reopen concluded loans."""
    sheet = _cla(
        "ts.pdf",
        [{"name": "Anna Beispiel", "kind": "individual", "domicile": "CH",
          "principal_amount": 50_000, "quote": "q"}],
        status="term_sheet",
        principal_total=_q(50_000),
    )
    executed = _cla(
        "ex.pdf",
        [{"name": "Anna Barbara Beispiel", "kind": "individual", "domicile": "CH",
          "principal_amount": 50_000, "quote": "q"}],
        principal_total=_q(50_000),
    )
    result = aggregate_clas([sheet, executed], run_date=date(2026, 1, 1))
    assert result["superseded_term_sheets"] == ["ts.pdf"]
    assert not result["open_term_sheets"]
    assert result["ten_twenty_rule"]["total_lenders_all_terms"] == 1


def test_conversion_window_parameter_respected() -> None:
    """Finding 10: the maturity window must be configurable."""
    cla = _cla(maturity_date=_q("2025-12-01"))
    tight = aggregate_clas(
        [cla], run_date=date(2026, 1, 5), conversion_window_days=30
    )
    loose = aggregate_clas(
        [cla], run_date=date(2026, 1, 5), conversion_window_days=60
    )
    assert tight["maturity"][0]["status"] == "expired_check_for_conversion"
    assert loose["maturity"][0]["status"] == "active"


def test_interest_above_safe_harbor_flags() -> None:
    """Finding 10b: high fixed interest must produce a finding."""
    findings = assess_cla(
        _cla(interest_mode=_q("fixed"), interest_rate_pct=_q(15)), RULES
    )
    assert any(f["item"] == "interest_rate" for f in findings)


def test_cross_snapshot_flags_class_wipeout() -> None:
    """Finding 3b: a class dropping to zero must fire, not skip."""
    previous = {
        "totals": {"by_class": [
            {"class_id": "common", "issued_total": 1000}
        ]},
        "stakeholders": [],
    }
    current = {"totals": {"by_class": []}, "stakeholders": []}
    findings = check_cross_snapshot(previous, current)
    assert any(f["check"] == "shrinking_share_class" for f in findings)


def test_esign_finds_envelope_in_kerned_tj_array() -> None:
    """Cut finding: TJ kerning offsets must not hide the envelope id."""
    from lib.captable.esign import scan_esign_markers

    blob = (b"[(Docu) -250 (sign Envel) 20 (ope ID: 642F9CEF-5BA7-4D50)] TJ")
    markers = scan_esign_markers(blob)
    assert markers["docusign_envelope_ids"] == ["642F9CEF-5BA7-4D50"]


def test_duplicate_note_labels_do_not_collapse() -> None:
    """Cut finding: two notes named identically must both be priced."""
    from lib.captable.model import Note, convert_in_round

    scenarios = convert_in_round(
        pre_money_valuation=4_000_000,
        new_investment=1_000_000,
        existing_shares={"founders": 1_000_000},
        notes=[
            Note("note", 100_000, discount_pct=20),
            Note("note", 200_000, discount_pct=20),
        ],
        methods=("pre_money",),
    )
    s = scenarios[0]
    assert len(s.note_prices) == 2
    # both balances convert at the discounted price (PPS 4.0 * 0.8 = 3.2)
    total_note_shares = sum(
        count for holder, count in s.shares.items() if "note" in holder
    )
    assert total_note_shares == pytest.approx(300_000 / 3.2)


# --- Ultra review (cloud) findings ------------------------------------------


def test_terms_group_key_normalizes_date_and_currency() -> None:
    """Ultra bug_005: '31.12.2027' and '2027-12-31' are the same terms."""
    from lib.captable.aggregation import terms_group_key

    a = _cla(maturity_date=_q("31.12.2027"), principal_currency=_q(" chf "))
    b = _cla(maturity_date=_q("2027-12-31"), principal_currency=_q("CHF"))
    assert terms_group_key(a) == terms_group_key(b)


def test_canonical_map_is_order_independent() -> None:
    """Ultra bug_001: short-name-first order must not double-count."""
    short_first = [
        _cla("a.pdf", [{"name": "Anna Beispiel", "kind": "individual",
                        "domicile": "CH", "principal_amount": 10_000,
                        "quote": "q"}]),
        _cla("b.pdf", [{"name": "Anna Barbara Beispiel", "kind": "individual",
                        "domicile": "CH", "principal_amount": 5_000,
                        "quote": "q"}]),
    ]
    result = aggregate_clas(short_first, run_date=date(2026, 1, 1))
    assert result["ten_twenty_rule"]["total_lenders_all_terms"] == 1
    assert len(result["per_lender"]) == 1
    assert result["per_lender"][0]["total_principal"] == 15_000


def test_resolve_as_of_ignores_unparseable_strings() -> None:
    """Ultra bug_002: 'around Q3 2025' must not beat a real ISO date."""
    from lib.captable.snapshot import resolve_as_of

    classification = {
        "documents": [
            {"filename": "a.md", "as_of_date": "2026-06-30"},
            {"filename": "b.md", "as_of_date": "around Q3 2025"},
        ]
    }
    best, _notes = resolve_as_of(
        {"as_of_date": {"value": None}}, classification, ["a.md", "b.md"]
    )
    assert best == "2026-06-30"


def test_compound_annual_survives_leap_day() -> None:
    """Ultra bug_003: Feb 29 execution date must not crash."""
    from lib.captable.model import loan_balance

    balance = loan_balance(
        100_000, 5, date(2024, 2, 29), date(2026, 6, 30),
        day_count="act/365", compounding="compound_annual",
    )
    assert balance > 100_000


def test_supersession_single_cla_variant_names_not_doubled() -> None:
    """Ultra bug_011: one executed CLA listing a person twice under variant
    names must not double its executed amount."""
    executed = _cla(
        "ex.pdf",
        [
            {"name": "Anna Beispiel", "kind": "individual", "domicile": "CH",
             "principal_amount": 100_000, "quote": "q"},
            {"name": "Anna Barbara Beispiel", "kind": "individual",
             "domicile": "CH", "principal_amount": 50_000, "quote": "q"},
        ],
        principal_total=_q(150_000),
    )
    sheet = _cla(
        "ts.pdf",
        [{"name": "Anna Beispiel", "kind": "individual", "domicile": "CH",
          "principal_amount": 150_000, "quote": "q"}],
        status="term_sheet",
        principal_total=_q(150_000),
    )
    result = aggregate_clas([executed, sheet], run_date=date(2026, 1, 1))
    assert result["superseded_term_sheets"] == ["ts.pdf"]
    # 150k executed matches the 150k term sheet: no discrepancy question
    assert not any(
        "clarify the difference" in q for q in result["diligence_questions"]
    )


# --- MCP user-test findings (2026-09-04 Desktop session) --------------------


def test_register_skew_downgrades_mismatch_severity() -> None:
    """A March register vs a June cap table is a dated comparison, not a
    hard inconsistency — mismatches report medium with the gap stated."""
    captable = {
        "as_of_date": {"value": "2026-06-30"},
        "stakeholders": [
            {"name": "Bruno Muster", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 250_000}]}
        ],
    }
    register = {
        "as_of_date": {"value": "2026-03-31"},
        "entries": [
            {"name": "Bruno Muster", "current_common": 300_000,
             "current_preferred": None, "current_participation_pct": 23,
             "first_acquisition_date": None, "last_change_date": None}
        ],
    }
    findings = check_register_reconciliation(captable, register)
    mismatch = next(f for f in findings if f["check"] == "register_mismatch")
    assert mismatch["severity"] == "medium"
    assert "2026-03" in mismatch["detail"] and "2026-06" in mismatch["detail"]


def test_diluted_rowsum_catches_double_counted_pool() -> None:
    from lib.captable.validate import check_diluted_rowsum

    captable = {
        "stakeholders": [
            {"name": "A", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 900_000}],
             "diluted_count": 900_000},
            {"name": "Pool", "kind": "authorized_capital", "role": "pool",
             "holdings": [], "diluted_count": 50_000},
            {"name": "Pool duplicate", "kind": "pool", "role": "pool",
             "holdings": [], "diluted_count": 50_000},
        ],
        "totals": {"by_class": [], "diluted_total": 950_000},
    }
    finding = check_diluted_rowsum(captable)[0]
    assert finding["status"] == "fail"
    assert "merged" in finding["detail"]


def test_scenarios_label_pools_and_report_founder_post_round() -> None:
    from skills.captable_analysis.captable_analysis import build_scenarios

    snapshot = {
        "as_of_date": "2026-06-30",
        "share_classes": [{"id": "common", "name": "Common",
                           "nominal_value": 0.1, "votes_per_share": None}],
        "stakeholders": [
            {"name": "Anna", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 600_000}],
             "diluted_count": 600_000, "invested_amount": 0},
            {"name": "Authorized Capital", "kind": "authorized_capital",
             "role": "pool", "holdings": [], "diluted_count": 100_000,
             "invested_amount": 0},
        ],
        "convertibles": [],
    }
    result = build_scenarios(
        snapshot, pre_money=7_000_000, investment=1_000_000,
        valuation_date=date(2026, 9, 4),
    )
    scenario = result["scenarios"][0]
    assert "[reserved pool] Authorized Capital" in scenario["ownership_pct"]
    assert "Authorized Capital" not in scenario["ownership_pct"]
    assert 0 < scenario["founders_post_round_pct"] < 100
    assert result["snapshot_as_of"] == "2026-06-30"
    assert any("accrued to the analysis date" in a
               for a in result["assumptions"])


def test_esign_not_applicable_for_non_pdf_sources() -> None:
    """User-test round 3: a markdown CLA has no PDF to scan — that is not
    evidence against execution and must not raise a diligence question."""
    cla = _cla("synthetic_cla.md")
    result = aggregate_clas(
        [cla], run_date=date(2026, 1, 1), esign_markers={}
    )
    entry = result["esignature"][0]
    assert entry["corroborated"] == "not_applicable"
    assert not any(
        "e-signature" in q for q in result["diligence_questions"]
    )
    # a scanned-but-empty PDF still raises the question
    result2 = aggregate_clas(
        [_cla("real.pdf")],
        run_date=date(2026, 1, 1),
        esign_markers={"real.pdf": {}},
    )
    assert result2["esignature"][0]["corroborated"] is False
    assert any("e-signature" in q for q in result2["diligence_questions"])

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

"""Tests for the deterministic CLA assessment and aggregation stages."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lib.captable.aggregation import (
    aggregate_clas,
    normalize_lender_name,
    terms_group_key,
)
from lib.captable.assessment import assess_cla, worst_severity
from lib.captable.esign import scan_esign_markers

RULES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "config"
        / "captable"
        / "assessment_rules.json"
    ).read_text(encoding="utf-8")
)


def _q(value, quote="q"):
    return {"value": value, "quote": quote}


def _cla(document="a.pdf", lenders=None, **overrides) -> dict:
    """A well-formed, market-standard executed CLA extraction."""
    base = {
        "document": document,
        "status": "executed",
        "lenders": lenders
        or [
            {
                "name": "Jane Angel",
                "kind": "individual",
                "domicile": "CH",
                "principal_amount": 100000,
                "quote": "q",
            }
        ],
        "principal_total": _q(100000),
        "principal_currency": _q("CHF"),
        "interest_mode": _q("fixed"),
        "interest_rate_pct": _q(5),
        "interest_day_count": _q("act/360"),
        "interest_compounding": _q("simple"),
        "maturity_date": _q("2027-06-30"),
        "qefr_present": _q(True),
        "qefr_min_raise": _q(1000000),
        "qefr_mandatory": _q(True),
        "coc_present": _q(True),
        "coc_mandatory": _q(False),
        "coc_repayment_multiple": _q(None, None),
        "maturity_conversion_present": _q(True),
        "maturity_conversion_mandatory": _q(False),
        "valuation_cap": _q(5000000),
        "discount_pct": _q(20),
        "discount_schedule": _q(None, None),
        "valuation_floor": _q(None, None),
        "denominator_basis": _q("fully_diluted"),
        "subordinated": _q(True),
        "subordination_scope": _q("loan_balance_full"),
        "mfn_clause": _q(True),
        "pro_rata_rights": _q(False, "q"),
        "conversion_capital_sources": _q(["consents"]),
        "shareholder_consents_referenced": _q(True),
        "sha_accession_required": _q(True),
        "signatures_complete": _q(True),
    }
    base.update(overrides)
    return base


# --- Stage 3: assessment ---------------------------------------------------


def test_market_standard_cla_has_no_bad_findings() -> None:
    findings = assess_cla(_cla(), RULES)
    assert worst_severity(findings) == "info"


def test_discount_above_tax_threshold_is_high() -> None:
    findings = assess_cla(_cla(discount_pct=_q(35)), RULES)
    item = next(f for f in findings if f["item"] == "discount")
    assert item["severity"] == "high"
    assert "33.33" in item["detail"]


def test_principal_only_subordination_is_severe() -> None:
    findings = assess_cla(
        _cla(subordination_scope=_q("principal_only")), RULES
    )
    item = next(f for f in findings if f["item"] == "subordination")
    assert item["severity"] == "severe"


def test_no_cap_without_maturity_is_high() -> None:
    findings = assess_cla(
        _cla(valuation_cap=_q(None, None), maturity_date=_q(None, None)),
        RULES,
    )
    item = next(f for f in findings if f["item"] == "valuation_cap")
    assert item["severity"] == "high"


def test_missing_conversion_capital_is_high() -> None:
    findings = assess_cla(
        _cla(
            conversion_capital_sources=_q([], None),
            shareholder_consents_referenced=_q(None, None),
        ),
        RULES,
    )
    item = next(f for f in findings if f["item"] == "conversion_capital")
    assert item["severity"] == "high"


# --- Stage 4: aggregation --------------------------------------------------


def test_lender_normalization() -> None:
    assert normalize_lender_name("  Anna  Barbara-Beispiel ") == (
        normalize_lender_name("anna barbara beispiel")
    )


def test_identical_terms_group_and_lender_dedup() -> None:
    """July batch on identical terms + one lender with an add-on."""
    july = [
        _cla("a.pdf", [{"name": "A One", "kind": "individual",
                        "domicile": "CH", "principal_amount": 15000,
                        "quote": "q"}]),
        _cla("b.pdf", [{"name": "B Two", "kind": "individual",
                        "domicile": "CH", "principal_amount": 5000,
                        "quote": "q"}]),
        _cla("c.pdf", [{"name": "A One", "kind": "individual",
                        "domicile": "CH", "principal_amount": 4000,
                        "quote": "q"}]),
    ]
    result = aggregate_clas(july, run_date=date(2026, 1, 1))
    assert len(result["identical_terms_groups"]) == 1
    group = result["identical_terms_groups"][0]
    assert group["lender_count"] == 2  # A One counted once
    assert result["outstanding_principal_total"] == 24000  # 3 loans summed
    a_row = next(
        r for r in result["per_lender"] if r["name"] == "A One"
    )
    assert a_row["loans"] == 2 and a_row["total_principal"] == 19000


def test_different_terms_make_two_groups() -> None:
    result = aggregate_clas(
        [_cla("a.pdf"), _cla("b.pdf", discount_pct=_q(25))],
        run_date=date(2026, 1, 1),
    )
    assert len(result["identical_terms_groups"]) == 2


def test_term_sheet_superseded_with_discrepancy_question() -> None:
    sheet = _cla(
        "ts.pdf",
        [{"name": "Fixture Angels", "kind": "entity", "domicile": "CH",
          "principal_amount": 50000, "quote": "q"}],
        status="term_sheet",
        principal_total=_q(50000),
    )
    executed = _cla(
        "ex.pdf",
        [{"name": "Fixture Angels", "kind": "entity", "domicile": "CH",
          "principal_amount": 20000, "quote": "q"}],
        principal_total=_q(20000),
    )
    result = aggregate_clas([sheet, executed], run_date=date(2026, 1, 1))
    assert result["superseded_term_sheets"] == ["ts.pdf"]
    assert result["outstanding_principal_total"] == 20000
    assert any("50,000" in q for q in result["diligence_questions"])


def test_expired_maturity_flagged_not_silently_outstanding() -> None:
    result = aggregate_clas(
        [_cla(maturity_date=_q("2025-06-30"))],
        run_date=date(2026, 9, 4),
    )
    finding = result["maturity"][0]
    assert finding["status"] == "expired_check_for_conversion"
    assert any("past maturity" in q for q in result["diligence_questions"])


def test_syndicate_caveat_on_ten_twenty() -> None:
    result = aggregate_clas(
        [
            _cla(
                lenders=[{"name": "Angels Pool", "kind": "syndicate",
                          "domicile": "CH", "principal_amount": 100000,
                          "quote": "q"}]
            )
        ],
        run_date=date(2026, 1, 1),
    )
    assert result["ten_twenty_rule"]["caveats"]


def test_unclaimed_esign_markers_raise_question() -> None:
    """A PDF that WAS scanned and yielded no markers raises the question
    (an unscanned/non-PDF source deliberately does not — see
    test_esign_not_applicable_for_non_pdf_sources)."""
    result = aggregate_clas(
        [_cla("a.pdf")],
        run_date=date(2026, 1, 1),
        esign_markers={"a.pdf": {}},
    )
    assert any(
        "no e-signature markers" in q for q in result["diligence_questions"]
    )


def test_esign_scan_finds_docusign_envelope() -> None:
    blob = b"junk Docusign Envelope ID: 642F9CEF-5BA7-4D50 more junk"
    markers = scan_esign_markers(blob)
    assert markers["docusign_envelope_ids"] == ["642F9CEF-5BA7-4D50"]


def test_esign_scan_finds_markers_inside_flate_stream() -> None:
    import zlib

    payload = zlib.compress(
        b"header Docusign Envelope ID: 8D144D1A-7658-4395 tail"
    )
    blob = b"%PDF-1.7\nstream\n" + payload + b"endstream\n%%EOF"
    markers = scan_esign_markers(blob)
    assert markers["docusign_envelope_ids"] == ["8D144D1A-7658-4395"]


def test_qefr_new_money_component_is_reported() -> None:
    findings = assess_cla(
        _cla(qefr_min_new_money=_q(8_000_000)), RULES
    )
    finding = next(f for f in findings if f["item"] == "qefr_trigger")
    assert "new" in finding["detail"] and "8,000,000" in finding["detail"]

    findings = assess_cla(_cla(qefr_min_new_money=_q(None)), RULES)
    finding = next(f for f in findings if f["item"] == "qefr_trigger")
    assert "no separate new-investor minimum" in finding["detail"]

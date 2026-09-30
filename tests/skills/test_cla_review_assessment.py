"""Lender-angle rules of cla_review over the fixture term sheet."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from lib.cla_review.assessment import (
    EVALUATORS,
    STATUS_ABSENT,
    STATUS_ACCEPTABLE,
    STATUS_FLAGGED,
    STATUS_NOT_EVALUATED,
    STATUS_OPEN_QUESTION,
    assess_lender_angle,
)
from lib.infrastructure.configuration import load_repository_config
from skills.cla_review.cla_review import load_rules
from tests.skills.test_captable_fixture_regressions import _term_sheet_extraction

ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = json.loads((ROOT / "tests/fixtures/captable/ground_truth.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 8, 15)


def _settings(*, approve_all: bool = False, deactivate_all: bool = False) -> dict:
    """The configured rules with their activation forced, so tests never depend on the current approval state."""
    settings = copy.deepcopy(load_repository_config("cla_review")["settings"])
    for rule in settings["rules"].values():
        if approve_all:
            rule["status"], rule["active"] = "approved", True
        elif deactivate_all:
            rule["status"], rule["active"] = "to verify", False
    load_rules(settings)
    return settings


def _sheet(**overrides) -> dict:
    """The fixture extraction with quoted fields overridden (``None`` plants an absence)."""
    sheet = _term_sheet_extraction()
    for field, value in overrides.items():
        sheet[field] = {"value": value, "quote": "q" if value is not None else None}
    return sheet


def _one(rule: str, sheet: dict, *, value=None, **context) -> tuple[str, str]:
    settings = _settings(approve_all=True)
    if value is not None:
        settings["rules"][rule]["value"] = value
    findings = {f["rule"]: f for f in assess_lender_angle(sheet, settings, as_of=AS_OF, **context)}
    return findings[rule]["status"], findings[rule]["detail"]


def test_inactive_rules_raise_open_questions_never_judgments():
    settings = _settings(deactivate_all=True)
    findings = assess_lender_angle(_term_sheet_extraction(), settings, as_of=AS_OF)
    assert {f["rule"] for f in findings} == set(settings["rules"]) - set(settings["inputs_not_rules"])
    for finding in findings:
        assert finding["status"] in {STATUS_OPEN_QUESTION, STATUS_NOT_EVALUATED}, finding
        assert finding["active"] is False
        assert finding["severity"] == "info"
        if finding["status"] == STATUS_OPEN_QUESTION:
            assert finding["detail"].startswith("Not judged: rule")
            assert finding["rule_status"] in finding["detail"]


def test_every_configured_rule_has_an_evaluator():
    settings = _settings()
    assert set(settings["rules"]) - set(settings["inputs_not_rules"]) == set(EVALUATORS)


@pytest.mark.parametrize("rule, overrides, expected, fragment", [
    ("discount_minimum_pct", {"discount_pct": None}, STATUS_ABSENT, "No conversion discount"),
    ("discount_minimum_pct", {"discount_pct": 10}, STATUS_FLAGGED, "below the proposed lender minimum"),
    ("discount_minimum_pct", {"discount_pct": 20}, STATUS_ACCEPTABLE, "meets"),
    ("discount_schedule_expected_above_months", {"maturity_date": None}, STATUS_NOT_EVALUATED, "cannot be measured"),
    ("discount_schedule_expected_above_months", {"maturity_date": "2027-02-15"}, STATUS_ACCEPTABLE, "only expected above"),
    ("discount_schedule_expected_above_months", {"discount_schedule": "10% then 20% after 12 months"}, STATUS_ACCEPTABLE, "with a discount schedule"),
    ("discount_schedule_expected_above_months", {}, STATUS_FLAGGED, "no discount schedule"),
    ("valuation_cap_required", {"valuation_cap": None}, STATUS_FLAGGED, "unbounded"),
    ("denominator_fully_diluted_expected", {"denominator_basis": "fully_diluted"}, STATUS_ACCEPTABLE, "investor-friendly"),
    ("denominator_fully_diluted_expected", {"denominator_basis": "issued_and_outstanding"}, STATUS_FLAGGED, "less investor-friendly"),
    ("denominator_fully_diluted_expected", {"denominator_basis": "unstated"}, STATUS_FLAGGED, "undefined"),
    ("qefr_threshold_minimum_multiple_of_aggregate_loan", {"qefr_min_raise": None}, STATUS_ABSENT, "No qualified-financing threshold"),
    ("qefr_threshold_minimum_multiple_of_aggregate_loan", {"qefr_min_raise": 400_000}, STATUS_FLAGGED, "below"),
    ("qefr_threshold_minimum_multiple_of_aggregate_loan", {"aggregate_amount_max": None, "aggregate_amount_min": None, "principal_total": None}, STATUS_NOT_EVALUATED, "aggregate loan amount is unknown"),
    ("qefr_threshold_maximum_multiple_of_round_target", {}, STATUS_NOT_EVALUATED, "round target"),
    ("maturity_conversion_required", {"maturity_conversion_present": True, "maturity_conversion_price": 9_000_000}, STATUS_ACCEPTABLE, "price of 9,000,000"),
    ("maturity_conversion_required", {"maturity_conversion_present": True}, STATUS_ACCEPTABLE, "not a number"),
    ("term_maximum_months", {"maturity_date": "2029-08-15"}, STATUS_FLAGGED, "exceeds the proposed maximum"),
    ("term_maximum_months", {"maturity_date": "2026-01-01"}, STATUS_FLAGGED, "before the run date"),
    ("term_maximum_months", {"maturity_date": "end of 2028"}, STATUS_NOT_EVALUATED, "not a date"),
    ("coc_repayment_multiple_minimum", {"coc_present": True}, STATUS_ABSENT, "without a repayment multiple"),
    ("coc_repayment_multiple_minimum", {"coc_present": True, "coc_repayment_multiple": 0.5}, STATUS_FLAGGED, "below the proposed minimum"),
    ("coc_repayment_multiple_minimum", {"coc_present": True, "coc_repayment_multiple": 2}, STATUS_ACCEPTABLE, "meets"),
    ("lender_majority_minimum_share_of_principal", {"investor_majority": None}, STATUS_FLAGGED, "undefined"),
    ("lender_majority_minimum_share_of_principal", {"investor_majority": "a simple majority of the principal"}, STATUS_FLAGGED, "50%"),
    ("lender_majority_minimum_share_of_principal", {"investor_majority": "the Lead Investor"}, STATUS_NOT_EVALUATED, "compare by hand"),
    ("lender_majority_minimum_share_of_principal", {}, STATUS_ACCEPTABLE, "67%"),
    ("exclusivity_flagged", {"exclusivity_present": False, "exclusivity_until": None}, STATUS_ACCEPTABLE, "No exclusivity"),
    ("legal_fees_each_party_own", {"legal_fees_each_party_own": None}, STATUS_ABSENT, "unstated"),
    ("legal_fees_each_party_own", {"legal_fees_each_party_own": False}, STATUS_FLAGGED, "not borne by each party"),
    ("binding_provisions_limited", {"binding_provisions": None}, STATUS_ABSENT, "does not distinguish"),
    ("binding_provisions_limited", {"binding_provisions": "confidentiality, costs, governing law"}, STATUS_ACCEPTABLE, "limited to"),
    ("documentation_seca_form_expected", {"documentation_form": "bespoke"}, STATUS_FLAGGED, "bespoke"),
    ("documentation_seca_form_expected", {"documentation_form": "unstated"}, STATUS_ABSENT, "unstated"),
    ("documentation_seca_form_expected", {"documentation_form": "seca_long_form"}, STATUS_ACCEPTABLE, "seca_long_form"),
    ("non_bank_rules", {}, STATUS_NOT_EVALUATED, "question 2"),
])
def test_evaluators_judge_their_inputs(rule, overrides, expected, fragment):
    status, detail = _one(rule, _sheet(**overrides))
    assert status == expected, detail
    assert fragment in detail


def test_interest_rule_needs_the_configured_safe_harbor_rate():
    assert _one("interest_safe_harbor_rate_pct", _sheet())[0] == STATUS_NOT_EVALUATED  # value null until verified
    assert _one("interest_safe_harbor_rate_pct", _sheet(), value=3.75)[0] == STATUS_FLAGGED  # fixture: 4%
    assert _one("interest_safe_harbor_rate_pct", _sheet(), value=4.5)[0] == STATUS_ACCEPTABLE
    assert _one("interest_safe_harbor_rate_pct", _sheet(interest_mode="safe_harbor_capped"), value=3.75)[0] == STATUS_ACCEPTABLE
    assert _one("interest_safe_harbor_rate_pct", _sheet(interest_rate_pct=None), value=3.75)[0] == STATUS_ABSENT


def test_non_bank_rule_reads_the_after_state_of_question_2():
    within = {"max_lenders_on_identical_terms": 6, "total_lenders_all_terms": 8}
    status, detail = _one("non_bank_rules", _sheet(), non_bank_counts=within)
    assert status == STATUS_ACCEPTABLE and "6 on identical terms (limit 10)" in detail
    status, detail = _one("non_bank_rules", _sheet(), non_bank_counts={**within, "max_lenders_on_identical_terms": 11})
    assert status == STATUS_FLAGGED and "withholding tax" in detail
    status, _ = _one("non_bank_rules", _sheet(), non_bank_counts=within, value={"identical_terms_lenders": 5, "total_lenders": 20})
    assert status == STATUS_FLAGGED  # the configured limit, not a hardcoded 10


def test_approved_rules_judge_the_fixture_as_the_answer_key_expects():
    expectations = GROUND_TRUTH["cla_term_sheet"]["lender_angle_expectations"]
    findings = {f["rule"]: f for f in assess_lender_angle(_term_sheet_extraction(), _settings(approve_all=True), as_of=AS_OF)}
    checked = 0
    for rule, expectation in expectations.items():
        if rule.startswith("_"):
            continue
        expected = STATUS_FLAGGED if expectation.startswith("flag") else STATUS_ACCEPTABLE
        assert findings[rule]["status"] == expected, (rule, findings[rule]["detail"])
        assert findings[rule]["active"] is True
        checked += 1
    assert checked >= 10
    assert findings["valuation_cap_required"]["severity"] == "info"
    assert findings["maturity_conversion_required"]["severity"] == "high"
    assert findings["coc_repayment_multiple_minimum"]["severity"] == "high"
    assert findings["exclusivity_flagged"]["severity"] == "medium"


def test_missing_inputs_are_named_not_faked():
    findings = {f["rule"]: f for f in assess_lender_angle(_term_sheet_extraction(), _settings(approve_all=True), as_of=AS_OF)}
    assert findings["qefr_threshold_maximum_multiple_of_round_target"]["status"] == STATUS_NOT_EVALUATED
    assert "round target" in findings["qefr_threshold_maximum_multiple_of_round_target"]["detail"]
    assert findings["interest_safe_harbor_rate_pct"]["status"] == STATUS_NOT_EVALUATED
    assert findings["non_bank_rules"]["status"] == STATUS_NOT_EVALUATED

    with_target = {f["rule"]: f for f in assess_lender_angle(
        _term_sheet_extraction(), _settings(approve_all=True), as_of=AS_OF, round_target=5_000_000,
    )}
    assert with_target["qefr_threshold_maximum_multiple_of_round_target"]["status"] == STATUS_ACCEPTABLE


def test_term_is_measured_from_the_as_of_date():
    late = {f["rule"]: f for f in assess_lender_angle(_term_sheet_extraction(), _settings(approve_all=True), as_of=date(2026, 7, 15))}
    assert late["term_maximum_months"]["status"] == STATUS_FLAGGED
    no_maturity = _term_sheet_extraction()
    no_maturity["maturity_date"] = {"value": None, "quote": None}
    findings = {f["rule"]: f for f in assess_lender_angle(no_maturity, _settings(approve_all=True), as_of=AS_OF)}
    assert findings["term_maximum_months"]["status"] == STATUS_NOT_EVALUATED


def test_unknown_rule_without_evaluator_fails_loudly():
    settings = _settings()
    settings["rules"]["mystery_rule"] = dict(settings["rules"]["exclusivity_flagged"])
    with pytest.raises(ValueError, match="mystery_rule"):
        assess_lender_angle(_term_sheet_extraction(), settings, as_of=AS_OF)

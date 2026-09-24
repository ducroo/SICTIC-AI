"""Lender-angle rules of cla_review over the fixture term sheet."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from lib.cla_review.assessment import (
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


def _settings(*, approve_all: bool = False) -> dict:
    settings = copy.deepcopy(load_repository_config("cla_review")["settings"])
    if approve_all:
        for rule in settings["rules"].values():
            rule["status"] = "approved"
            rule["active"] = True
    load_rules(settings)
    return settings


def test_inactive_rules_raise_open_questions_never_judgments():
    findings = assess_lender_angle(_term_sheet_extraction(), _settings(), as_of=AS_OF)
    assert {f["rule"] for f in findings} == set(_settings()["rules"]) - set(_settings()["inputs_not_rules"])
    for finding in findings:
        assert finding["status"] in {STATUS_OPEN_QUESTION, STATUS_NOT_EVALUATED}, finding
        assert finding["active"] is False
        assert finding["severity"] == "info"
        if finding["status"] == STATUS_OPEN_QUESTION:
            assert finding["detail"].startswith("Not judged: rule")
            assert finding["rule_status"] in finding["detail"]


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

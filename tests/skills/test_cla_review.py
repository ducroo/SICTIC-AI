"""Slice-0 contracts of cla_review: configuration, references, fixture, stub."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lib.infrastructure.configuration import load_repository_config
from skills.cla_review.cla_review import (
    APPROVED_STATUS,
    NOT_IMPLEMENTED,
    active_rules,
    cla_review,
    load_reference_term_sheets,
    load_rules,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/captable"
GROUND_TRUTH = json.loads((FIXTURE / "ground_truth.json").read_text(encoding="utf-8"))
TERM_SHEET = (FIXTURE / "synthetic_cla_term_sheet.md").read_text(encoding="utf-8")


def _settings() -> dict:
    return copy.deepcopy(load_repository_config("cla_review")["settings"])


def test_every_configured_rule_is_complete_and_inactive():
    rules = load_rules(_settings())
    assert len(rules) >= 16
    assert active_rules(rules) == {}
    for name, rule in rules.items():
        assert rule["source"].strip(), name
        assert rule["status"] != APPROVED_STATUS, name


def test_only_approved_rules_may_be_active():
    settings = _settings()
    settings["rules"]["valuation_cap_required"]["active"] = True
    with pytest.raises(ValueError, match="only 'approved' rules may be active"):
        load_rules(settings)

    settings["rules"]["valuation_cap_required"]["status"] = APPROVED_STATUS
    assert set(active_rules(load_rules(settings))) == {"valuation_cap_required"}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda s: s["rules"]["term_maximum_months"].pop("source"), "lacks"),
        (lambda s: s["rules"]["term_maximum_months"].update(status="guess"), "unknown status"),
        (lambda s: s["rules"]["term_maximum_months"].update(active="yes"), "must be a boolean"),
        (lambda s: s.update(rules={}), "non-empty"),
    ],
)
def test_malformed_rule_tables_fail_loudly(mutate, message):
    settings = _settings()
    mutate(settings)
    with pytest.raises(ValueError, match=message):
        load_rules(settings)


def test_both_seca_term_sheets_are_configured():
    references = load_reference_term_sheets(load_repository_config("cla_review"))
    assert set(references) == {
        "seca_cla_term_sheet_short_form_february_2025",
        "seca_cla_term_sheet_long_form_february_2025",
    }
    for content in references.values():
        assert "<!-- sictic-page:1 -->" in content
        assert "consents to the use, reproduction and transmission" in content
        assert "Note:" in content, "the SECA drafting notes must survive conversion"
    assert "Conditions Precedent" in references["seca_cla_term_sheet_long_form_february_2025"]


def test_reference_term_sheets_are_required():
    with pytest.raises(ValueError, match="short-form and long-form"):
        load_reference_term_sheets({"reference_term_sheets": {"only_one": "x"}})


def test_fixture_term_sheet_plants_the_recorded_absences():
    truth = GROUND_TRUTH["cla_term_sheet"]
    assert truth["status"] == "term_sheet"
    assert "(unsigned)" in TERM_SHEET
    lowered = TERM_SHEET.lower()
    for phrase in ("change of control", "most favored", "most favoured", "pro rata", "pro-rata", "floor", "fully diluted", "issued and outstanding"):
        assert phrase not in lowered, phrase
    assert truth["coc_present"] is False
    assert truth["maturity_conversion_present"] is False
    assert truth["denominator_basis"] == "unstated"
    for field in ("coc_present", "maturity_conversion_present", "denominator_basis", "mfn_clause", "pro_rata_rights", "valuation_floor"):
        assert field in truth["expected_missing_terms"], field
    for planted in ("CHF 500,000", "CHF 300,000", "Fixture Angels", "CHF 12,000,000", "discount of 20%", "two thirds", "Exclusivity", "SECA CLA Model Documentation (short form)"):
        assert planted in TERM_SHEET, planted


@pytest.mark.asyncio
async def test_stub_validates_configuration_then_fails_clearly(mock_env):
    with pytest.raises(ValueError, match="not implemented yet"):
        await cla_review("example-startup")
    with pytest.raises(ValueError, match="positive"):
        await cla_review("example-startup", ticket=0)
    assert "docs/cla-review-design.md" in NOT_IMPLEMENTED

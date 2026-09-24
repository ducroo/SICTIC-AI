"""cla_review question 2 (slice 2): the member's conversion and the existing loans on the fixture."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from lib.cla_review.conversion import ASSUMPTION, EVIDENCED, EXPLICIT, my_conversion, resolve_inputs
from lib.cla_review.loans import loan_context
from lib.infrastructure.configuration import load_repository_config
from tests.skills.test_captable_fixture_regressions import _term_sheet_extraction

ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = json.loads((ROOT / "tests/fixtures/captable/ground_truth.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 8, 15)


def _settings() -> dict:
    return copy.deepcopy(load_repository_config("cla_review")["settings"])


def _q(value):
    return {"value": value, "quote": "q" if value is not None else None}


def _executed_cla() -> dict:
    truth = GROUND_TRUTH["cla"]
    cla = {"document": truth["document"], "status": "executed", "dataset": "synthcap",
           "lenders": [{"name": l["name"], "kind": l["kind"], "domicile": l["domicile"],
                        "principal_amount": l["principal_amount"], "quote": "q"} for l in truth["lenders"]]}
    for field in ("principal_total", "principal_currency", "interest_mode", "interest_rate_pct", "interest_day_count",
                  "interest_compounding", "execution_date", "maturity_date", "valuation_cap", "discount_pct",
                  "valuation_floor", "qefr_min_raise", "mfn_clause", "pro_rata_rights", "denominator_basis",
                  "subordinated", "subordination_scope"):
        cla[field] = _q(truth[field])
    return cla


def _snapshot() -> dict:
    return {
        "share_classes": [{"id": "common", "name": "Common", "nominal_value": 0.10, "votes_per_share": None}],
        "stakeholders": [
            {"name": "Founder", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 600_000}], "diluted_count": 600_000, "invested_amount": 0},
            {"name": "Angel", "kind": "individual", "role": "investor",
             "holdings": [{"class_id": "common", "count": 300_000}], "diluted_count": 300_000, "invested_amount": 450_000},
            {"name": "Treasury", "kind": "treasury", "role": "company",
             "holdings": [{"class_id": "common", "count": 50_000}], "diluted_count": None, "invested_amount": 0},
        ],
        "convertibles": [_executed_cla()],
    }


def _term_sheet() -> dict:
    return {**_term_sheet_extraction(), "document": "synthetic_cla_term_sheet.md", "dataset": "synthcap"}


def test_inputs_are_resolved_and_labelled_before_any_number():
    inputs, omitted, _ = resolve_inputs(_term_sheet(), _snapshot(), _settings(), ticket=None, as_of=AS_OF)
    assert omitted == []
    assert inputs["ticket"] == {"value": 100_000.0, "source": ASSUMPTION, "note": inputs["ticket"]["note"]}
    assert "divided by the configured member count 5" in inputs["ticket"]["note"]
    assert inputs["other_new_lenders"]["value"] == 400_000.0
    assert inputs["round_investment"] == {"value": 3_000_000.0, "source": ASSUMPTION, "note": inputs["round_investment"]["note"]}
    assert inputs["currency"] == {"value": "CHF", "source": EVIDENCED, "note": None}
    assert inputs["denominator"]["value"] == {"basis": "fully_diluted", "shares": 900_000}
    assert inputs["denominator"]["source"] == ASSUMPTION  # the fixture leaves the basis unstated
    assert inputs["conversion_dates"]["value"] == ["2026-08-15", "2028-08-15"]
    assert inputs["valuation_grid"]["value"][0] == 6_000_000 and inputs["valuation_grid"]["value"][-1] == 36_000_000

    explicit, _, _ = resolve_inputs(_term_sheet(), _snapshot(), _settings(), ticket=25_000, as_of=AS_OF)
    assert explicit["ticket"] == {"value": 25_000.0, "source": EXPLICIT, "note": "given on the command line"}
    assert explicit["other_new_lenders"]["value"] == 475_000.0


def test_conversion_table_crossover_and_binding_terms():
    result = my_conversion(_term_sheet(), _snapshot(), _settings(), ticket=None, as_of=AS_OF)
    assert result["omitted"] == []
    assert result["crossover_valuation"] == 15_000_000
    rows = {(r["conversion_date"], r["pre_money"]): r for r in result["scenarios"]}
    assert len(rows) == 12  # two dates x six grid points
    assert rows[("2026-08-15", 6_000_000)]["binding_term"] == "discount"
    assert rows[("2026-08-15", 36_000_000)]["binding_term"] == "cap"
    assert rows[("2026-08-15", 12_000_000)]["my_price"] == pytest.approx(12_000_000 / 900_000 * 0.8, abs=1e-4)
    assert rows[("2026-08-15", 36_000_000)]["my_price"] == pytest.approx(12_000_000 / 900_000, abs=1e-4)
    # no interest at the run date, two years of 4% simple interest at maturity
    assert result["balances"]["2026-08-15"] == 100_000
    assert result["balances"]["2028-08-15"] == pytest.approx(108_000, abs=30)
    assert rows[("2028-08-15", 12_000_000)]["my_shares"] > rows[("2026-08-15", 12_000_000)]["my_shares"]
    for row in result["scenarios"]:
        assert 0 < row["my_ownership_pct"] < row["other_new_lenders_ownership_pct"]
        assert row["existing_loans_ownership_pct"] > 0 and row["new_investor_ownership_pct"] > 0
    assert result["stamp_duty"]["duty"] > 0
    assert result["stamp_duty"]["round_contribution"] == pytest.approx(3_000_000 + 500_000 + 250_000 * (1 + 0.05 * 212 / 365), rel=1e-4)


def test_missing_inputs_omit_the_calculation_with_a_reason():
    sheet = _term_sheet()
    sheet["aggregate_amount_max"] = _q(None)
    sheet["aggregate_amount_min"] = _q(None)
    result = my_conversion(sheet, _snapshot(), _settings(), ticket=None, as_of=AS_OF)
    assert result["scenarios"] == []
    assert any("no ticket" in item["reason"] for item in result["omitted"])
    assert result["crossover_valuation"] == 15_000_000  # needs only cap and discount

    uncapped = _term_sheet()
    uncapped["valuation_cap"] = _q(None)
    result = my_conversion(uncapped, _snapshot(), _settings(), ticket=50_000, as_of=AS_OF)
    assert result["crossover_valuation"] is None
    assert any("uncapped" in item["reason"] for item in result["omitted"])
    settings = _settings()
    settings["rules"]["valuation_grid_absolute"]["value"] = [5_000_000, 10_000_000]
    result = my_conversion(uncapped, _snapshot(), _settings() | {"rules": settings["rules"]}, ticket=50_000, as_of=AS_OF)
    assert {r["pre_money"] for r in result["scenarios"]} == {5_000_000, 10_000_000}
    assert all(r["binding_term"] == "discount" for r in result["scenarios"])

    foreign = _snapshot()
    foreign["convertibles"][0]["principal_currency"] = _q("USD")
    result = my_conversion(_term_sheet(), foreign, _settings(), ticket=50_000, as_of=AS_OF)
    assert result["scenarios"] == []
    assert all("another currency" in item["reason"] for item in result["omitted"])


def test_loan_context_matches_the_answer_key():
    expected = GROUND_TRUTH["cla_term_sheet"]["question_2_expectations"]
    context = loan_context(_term_sheet(), _snapshot(), _settings(), ticket=100_000, as_of=AS_OF)
    assert [row["role"] for row in context["comparison"]] == ["term sheet under review", "executed loan"]
    assert context["comparison"][1]["valuation_cap"] == 8_000_000 and context["comparison"][0]["valuation_cap"] == 12_000_000
    assert context["mfn"]["existing_loans_with_mfn"] == ["synthetic_cla.md"]
    assert context["mfn"]["term_sheet_more_favourable_than"] == []
    assert context["mfn"]["existing_more_favourable_than_term_sheet"] == [
        {"document": "synthetic_cla.md", "terms": ["lower valuation cap", "higher interest"]}
    ]
    assert any("no MFN clause" in reading for reading in context["mfn"]["readings"])
    assert context["identical_terms"] == {"joins_existing_group": False, "documents": []}
    before, after = context["ten_twenty"]["before"], context["ten_twenty"]["after"]
    for key in ("max_lenders_on_identical_terms", "total_lenders_all_terms"):
        assert before[key] == expected["ten_twenty_before"][key], key
        assert after[key] == expected["ten_twenty_after"][key], key
    assert context["ten_twenty"]["term_sheet_group_lenders_after"] == 6
    assert after["ten_rule"] == "within" and after["twenty_rule"] == "within"
    assert [m["document"] for m in context["maturities"]] == ["synthetic_cla.md", "synthetic_cla_term_sheet.md"]


def test_member_count_drives_the_after_state_and_crosses_the_ten_rule():
    settings = _settings()
    settings["rules"]["member_count_n"]["value"] = 12
    context = loan_context(_term_sheet(), _snapshot(), settings, ticket=None, as_of=AS_OF)
    assert context["ten_twenty"]["after"]["max_lenders_on_identical_terms"] == 13
    assert context["ten_twenty"]["after"]["ten_rule"] == "exceeded"
    assert context["ten_twenty"]["before"]["ten_rule"] == "within"


def test_term_sheet_already_in_the_snapshot_is_not_double_counted():
    snapshot = _snapshot()
    snapshot["convertibles"].append(_term_sheet())  # captable_build classified it as term_sheet
    context = loan_context(_term_sheet(), snapshot, _settings(), ticket=None, as_of=AS_OF)
    assert context["executed_count"] == 1
    assert context["ten_twenty"]["after"]["total_lenders_all_terms"] == 8

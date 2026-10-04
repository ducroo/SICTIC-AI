"""cla_review question 2 (slice 2): the member's conversion and the existing loans on the fixture."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from lib.cla_review.conversion import ASSUMPTION, EVIDENCED, EXPLICIT, crossover_valuation, my_conversion, resolve_inputs
from lib.cla_review.loans import loan_context
from lib.infrastructure.configuration import load_repository_config
from tests.skills.test_captable_fixture_regressions import _term_sheet_extraction

ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = json.loads((ROOT / "tests/fixtures/captable/ground_truth.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 8, 15)


def _settings() -> dict:
    return copy.deepcopy(load_repository_config("cla_review")["settings"])


def _setting(name: str):
    return _settings()["rules"][name]["value"]


CAP = 12_000_000  # the fixture term sheet's cap; the answer key's crossover follows from it and the 20% discount


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
    members = _setting("member_count_n")
    assert inputs["ticket"] == {"value": 500_000 / members, "source": ASSUMPTION, "note": inputs["ticket"]["note"]}
    assert f"divided by the configured member count {members}" in inputs["ticket"]["note"]
    assert inputs["other_new_lenders"]["value"] == 500_000 - 500_000 / members
    assert inputs["participating_loans"] == {
        "value": [{"document": "synthetic_cla.md", "principal": 250_000, "currency": "CHF"}], "source": EVIDENCED,
        "note": inputs["participating_loans"]["note"],
    }
    assert inputs["round_investment"] == {"value": 3_000_000.0, "source": ASSUMPTION, "note": inputs["round_investment"]["note"]}
    assert inputs["currency"] == {"value": "CHF", "source": EVIDENCED, "note": None}
    assert inputs["denominator"]["value"] == {"basis": "fully_diluted", "shares": 900_000}
    assert inputs["denominator"]["source"] == ASSUMPTION  # the fixture leaves the basis unstated
    assert inputs["conversion_dates"]["value"] == ["2026-08-15", "2028-08-15"]
    multiples = _setting("valuation_grid_multiples_of_cap")
    assert inputs["valuation_grid"]["value"] == [CAP * m for m in multiples]

    explicit, _, _ = resolve_inputs(_term_sheet(), _snapshot(), _settings(), ticket=25_000, as_of=AS_OF)
    assert explicit["ticket"] == {"value": 25_000.0, "source": EXPLICIT, "note": "given on the command line"}
    assert explicit["other_new_lenders"]["value"] == 475_000.0


def test_conversion_table_crossover_and_binding_terms():
    result = my_conversion(_term_sheet(), _snapshot(), _settings(), ticket=100_000, as_of=AS_OF)
    assert result["omitted"] == []
    assert result["crossover_valuation"] == 15_000_000
    grid = [CAP * m for m in _setting("valuation_grid_multiples_of_cap")]
    rows = {(r["conversion_date"], r["pre_money"]): r for r in result["scenarios"]}
    assert len(rows) == 2 * len(grid)  # two dates x the grid
    assert rows[("2026-08-15", min(grid))]["binding_term"] == "discount"
    assert rows[("2026-08-15", max(grid))]["binding_term"] == "cap"
    assert rows[("2026-08-15", CAP)]["my_price"] == pytest.approx(CAP / 900_000 * 0.8, abs=1e-4)
    assert rows[("2026-08-15", max(grid))]["my_price"] == pytest.approx(CAP / 900_000, abs=1e-4)
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
    assert result["stamp_duty"] is None  # never computed on an incomplete converting stack
    assert {item["calculation"] for item in result["omitted"]} == {"my conversion at 2026-08-15", "my conversion at 2028-08-15", "stamp duty"}
    assert all("another currency" in item["reason"] or "other currency" in item["reason"] for item in result["omitted"])

    unstated = _snapshot()
    unstated["convertibles"][0]["principal_total"] = _q(None)
    result = my_conversion(_term_sheet(), unstated, _settings(), ticket=50_000, as_of=AS_OF)
    assert result["scenarios"]  # the loan is left out of the stack, with a note
    assert any("principal unstated" in text for text in result["assumptions"])
    assert result["stamp_duty"] is None
    assert any(item["calculation"] == "stamp duty" and "principal unstated" in item["reason"] for item in result["omitted"])


def test_crossover_follows_the_denominator_of_the_cap():
    assert crossover_valuation(5_000_000, 20, cap_denominator=None, round_denominator=None) == 6_250_000
    assert crossover_valuation(5_000_000, 20, cap_denominator=125_000, round_denominator=125_000) == 6_250_000
    # the cap prices on 100k issued shares, the round on 125k fully diluted: the cap binds later
    assert crossover_valuation(5_000_000, 20, cap_denominator=100_000, round_denominator=125_000) == 7_812_500

    snapshot = _snapshot()
    snapshot["stakeholders"].append({"name": "ESOP", "kind": "pool", "role": "pool",
                                     "holdings": [{"class_id": "common", "count": 100_000}], "diluted_count": 100_000, "invested_amount": 0})
    sheet = _term_sheet()
    sheet["denominator_basis"] = _q("issued_and_outstanding")
    result = my_conversion(sheet, snapshot, _settings(), ticket=100_000, as_of=AS_OF)
    assert result["inputs"]["denominator"]["value"] == {"basis": "issued_and_outstanding", "shares": 900_000}
    crossover = result["crossover_valuation"]
    assert crossover == pytest.approx(CAP * 1_000_000 / 900_000 / 0.8, abs=1)
    below = [r for r in result["scenarios"] if r["conversion_date"] == "2026-08-15" and r["pre_money"] < crossover]
    above = [r for r in result["scenarios"] if r["conversion_date"] == "2026-08-15" and r["pre_money"] > crossover]
    assert below and above
    assert all(r["binding_term"] == "discount" for r in below) and all(r["binding_term"] == "cap" for r in above)


def test_maturity_before_the_run_date_is_not_a_conversion_date():
    result = my_conversion(_term_sheet(), _snapshot(), _settings(), ticket=100_000, as_of=date(2029, 1, 1))
    assert result["inputs"]["conversion_dates"]["value"] == ["2029-01-01"]
    assert "lies before it" in result["inputs"]["conversion_dates"]["note"]
    assert {r["conversion_date"] for r in result["scenarios"]} == {"2029-01-01"}


def test_ticket_interest_respects_the_safe_harbor_cap_like_the_existing_loans():
    sheet = _term_sheet()
    sheet["interest_mode"] = _q("safe_harbor_capped")
    sheet["interest_safe_harbor_rate_pct"] = _q(3.0)
    result = my_conversion(sheet, _snapshot(), _settings(), ticket=100_000, as_of=AS_OF)
    assert result["inputs"]["interest"]["value"]["rate_pct"] == 3.0
    assert any("lower of 4% and the safe-harbor rate" in text for text in result["assumptions"])
    assert result["balances"]["2028-08-15"] == pytest.approx(106_000, abs=30)


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


def test_maturities_sort_as_dates_not_strings():
    snapshot = _snapshot()
    snapshot["convertibles"][0]["maturity_date"] = _q("31.12.2027")  # captable_build keeps the extracted spelling
    context = loan_context(_term_sheet(), snapshot, _settings(), ticket=None, as_of=AS_OF)
    assert [m["maturity_date"] for m in context["maturities"]] == ["31.12.2027", "2028-08-15"]


def test_member_count_drives_the_after_state_and_crosses_the_ten_rule():
    settings = _settings()
    settings["rules"]["member_count_n"]["value"] = 12
    context = loan_context(_term_sheet(), _snapshot(), settings, ticket=None, as_of=AS_OF)
    assert context["ten_twenty"]["after"]["max_lenders_on_identical_terms"] == 13  # the lead plus twelve members
    assert context["ten_twenty"]["after"]["ten_rule"] == "exceeded"
    assert context["ten_twenty"]["before"]["ten_rule"] == "within"


def test_term_sheet_already_in_the_snapshot_is_not_double_counted():
    snapshot = _snapshot()
    snapshot["convertibles"].append(_term_sheet())  # captable_build classified it as term_sheet
    context = loan_context(_term_sheet(), snapshot, _settings(), ticket=None, as_of=AS_OF)
    assert context["executed_count"] == 1
    assert context["ten_twenty"]["after"]["total_lenders_all_terms"] == 8

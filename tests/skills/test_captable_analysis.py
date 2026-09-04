"""Tests for the deterministic parts of captable_analysis (no LLM)."""

from __future__ import annotations

from datetime import date

from lib.captable.rubric import apply_rubric, ownership_by_role
from skills.captable_analysis.captable_analysis import build_scenarios


def _snapshot() -> dict:
    return {
        "share_classes": [
            {"id": "common", "name": "Common", "nominal_value": 0.10,
             "votes_per_share": None},
        ],
        "stakeholders": [
            {"name": "Founder", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 600_000}],
             "diluted_count": 600_000, "invested_amount": 0},
            {"name": "Angel", "kind": "individual", "role": "investor",
             "holdings": [{"class_id": "common", "count": 300_000}],
             "diluted_count": 300_000, "invested_amount": 450_000},
            {"name": "Gone Guy", "kind": "individual", "role": "departed",
             "holdings": [{"class_id": "common", "count": 150_000}],
             "diluted_count": 150_000, "invested_amount": 0},
            {"name": "Treasury", "kind": "treasury", "role": "company",
             "holdings": [{"class_id": "common", "count": 50_000}],
             "diluted_count": None, "invested_amount": 0},
        ],
        "fully_diluted_definition": {"value": "unstated", "quote": None},
        "convertibles": [
            {
                "document": "cla.md",
                "status": "executed",
                "principal_total": {"value": 100_000},
                "interest_rate_pct": {"value": 5},
                "interest_day_count": {"value": "act/365"},
                "interest_compounding": {"value": "simple"},
                "execution_date": {"value": "2025-01-01"},
                "valuation_cap": {"value": 4_000_000},
                "discount_pct": {"value": 20},
                "valuation_floor": {"value": None},
                "qefr_min_raise": {"value": 2_000_000},
            }
        ],
        "validation": [],
        "diligence_questions": [],
        "aggregation": {},
    }


def test_ownership_excludes_treasury() -> None:
    pct = ownership_by_role(_snapshot())
    total = sum(pct.values())
    assert abs(total - 100.0) < 1e-6
    import pytest

    assert pct["founder"] == pytest.approx(600_000 / 1_050_000 * 100)


def test_rubric_flags_dead_equity_and_fd_definition() -> None:
    findings = {f["item"]: f for f in apply_rubric(_snapshot())}
    assert findings["dead_equity"]["status"] == "flag"  # 14.3% > 10%
    assert findings["fd_definition"]["status"] == "flag"
    assert findings["founder_majority"]["status"] == "ok"  # 57%


def test_build_scenarios_defaults_and_interest() -> None:
    result = build_scenarios(
        _snapshot(), valuation_date=date(2026, 1, 1)
    )
    # defaults: pre-money = largest cap, investment = QEFR minimum
    assert result["hypothetical_round"]["pre_money"] == 4_000_000
    assert result["hypothetical_round"]["investment"] == 2_000_000
    assert any("valuation cap" in a for a in result["assumptions"])
    # one year of 5% simple interest on 100k
    balance = list(result["note_balances"].values())[0]
    assert abs(balance - 105_000) < 100
    # three methods, each with full ownership tables summing to ~100
    assert {s["method"] for s in result["scenarios"]} == {
        "pre_money", "percentage_ownership", "dollars_invested"
    }
    for scenario in result["scenarios"]:
        assert abs(sum(scenario["ownership_pct"].values()) - 100.0) < 0.1


def test_explicit_round_parameters_override_defaults() -> None:
    result = build_scenarios(
        _snapshot(),
        pre_money=10_000_000,
        investment=3_000_000,
        valuation_date=date(2026, 1, 1),
    )
    assert result["hypothetical_round"]["pre_money"] == 10_000_000
    assert result["hypothetical_round"]["investment"] == 3_000_000

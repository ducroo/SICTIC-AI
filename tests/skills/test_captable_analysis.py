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


def _snapshot_with_safe_harbor(safe_harbor: float | None) -> dict:
    snapshot = _snapshot()
    cla = snapshot["convertibles"][0]
    cla["interest_rate_pct"] = {"value": 8}
    cla["interest_mode"] = {"value": "safe_harbor_capped"}
    cla["interest_safe_harbor_rate_pct"] = {"value": safe_harbor}
    return snapshot


def test_safe_harbor_cap_is_applied_to_the_balance() -> None:
    """Real-data verification (round 4): the extraction knew safe_harbor_capped but
    the analysis accrued the full ceiling rate (~CHF 464k overstated)."""
    result = build_scenarios(
        _snapshot_with_safe_harbor(1.75), valuation_date=date(2026, 1, 1)
    )
    balance = list(result["note_balances"].values())[0]
    # one year of 1.75% (the safe-harbor figure), NOT 8%
    assert abs(balance - 101_750) < 100
    assert any("safe-harbor" in a for a in result["assumptions"])


def test_unquantified_safe_harbor_uses_ceiling_and_discloses() -> None:
    result = build_scenarios(
        _snapshot_with_safe_harbor(None), valuation_date=date(2026, 1, 1)
    )
    balance = list(result["note_balances"].values())[0]
    assert abs(balance - 108_000) < 100  # ceiling rate, but disclosed
    assert any("OVERSTATES" in a for a in result["assumptions"])


def test_fixed_maturity_price_block() -> None:
    """Real-data verification (round 4): a fixed maturity conversion price governs
    the expired-loan scenario and implies the company's own value anchor."""
    snapshot = _snapshot()
    snapshot["convertibles"][0]["maturity_conversion_price"] = {
        "value": 1.2981
    }
    result = build_scenarios(snapshot, valuation_date=date(2026, 1, 1))
    entries = result["maturity_conversion_at_fixed_price"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["price_per_share"] == 1.2981
    # balance (105k at 5%) divided by the fixed price
    assert abs(entry["implied_shares_at_balance"] - 105_000 / 1.2981) < 1
    # price x existing fully-diluted shares (1,050,000; treasury excluded)
    assert (
        abs(entry["implied_company_value_at_price"] - 1.2981 * 1_050_000)
        < 1
    )
    assert any("MATURITY" in a for a in result["assumptions"])


def test_no_fixed_maturity_price_means_empty_block() -> None:
    result = build_scenarios(_snapshot(), valuation_date=date(2026, 1, 1))
    assert result["maturity_conversion_at_fixed_price"] == []


# --- Currency handling (review point 1 on PR #61) ---------------------------


def _cla(document: str, principal: float, currency: str | None, **extra) -> dict:
    cla = {
        "document": document,
        "status": "executed",
        "principal_total": {"value": principal},
        "principal_currency": {"value": currency},
        "interest_rate_pct": {"value": 0},
        "interest_day_count": {"value": "act/365"},
        "interest_compounding": {"value": "simple"},
        "execution_date": {"value": "2025-01-01"},
        "valuation_cap": {"value": 4_000_000},
        "discount_pct": {"value": 20},
        "valuation_floor": {"value": None},
        "qefr_min_raise": {"value": 2_000_000},
    }
    cla.update(extra)
    return cla


def _mixed_snapshot() -> dict:
    snapshot = _snapshot()
    snapshot["convertibles"] = [
        _cla("chf.md", 100_000, "CHF"),
        # at 0.5 CHF/USD this is the same loan: 100k CHF under a 4M CHF cap
        _cla("usd.md", 200_000, "usd", valuation_cap={"value": 8_000_000}),
    ]
    return snapshot


def test_mixed_currencies_without_rates_refuse_to_sum() -> None:
    result = build_scenarios(_mixed_snapshot(), valuation_date=date(2026, 1, 1))
    assert result["currency"] == "CHF"
    assert result["scenarios"] == []
    assert result["notes_without_fx_rate"] == ["lenders of usd.md"]
    flag = next(f for f in result["scenario_flags"]
                if f["item"] == "mixed_currencies")
    assert flag["severity"] == "high"
    assert "usd.md (USD)" in flag["detail"]
    assert result["stamp_duty"]["estimate_chf"] is None
    assert result["stamp_duty_estimate_chf"] is None
    # balances stay reported in their own currency, never mixed
    assert result["note_currencies"] == {
        "lenders of chf.md": "CHF", "lenders of usd.md": "USD"
    }


def test_mixed_currencies_with_rates_convert_everything() -> None:
    result = build_scenarios(
        _mixed_snapshot(),
        valuation_date=date(2026, 1, 1),
        fx_rates={"usd": 0.5},
    )
    assert result["scenarios"], "rates supplied -> scenarios computed"
    assert not any(f["item"] == "mixed_currencies"
                   for f in result["scenario_flags"])
    assert result["fx_rates"] == {"USD": 0.5}
    assert any("0.5 CHF per 1 USD" in a for a in result["assumptions"])
    # the USD note converts at the rate (balance AND cap): 200k USD under an
    # 8M USD cap -> 100k CHF under a 4M CHF cap, identical to the CHF note,
    # so both receive the same ownership in every method
    for scenario in result["scenarios"]:
        shares_chf = scenario["ownership_pct"]["lenders of chf.md"]
        shares_usd = scenario["ownership_pct"]["lenders of usd.md"]
        assert abs(shares_chf - shares_usd) < 0.01
    assert result["stamp_duty"]["estimate_chf"] is not None


def test_single_foreign_currency_sets_scenario_currency_and_no_stamp_duty() -> None:
    snapshot = _snapshot()
    snapshot["convertibles"] = [_cla("eur.md", 100_000, "EUR")]
    result = build_scenarios(snapshot, valuation_date=date(2026, 1, 1))
    assert result["currency"] == "EUR"
    assert result["hypothetical_round"]["currency"] == "EUR"
    assert result["scenarios"]
    assert result["stamp_duty"]["estimate_chf"] is None
    assert "EUR" in result["stamp_duty"]["note"]


def test_unstated_currency_is_assumed_and_disclosed() -> None:
    snapshot = _snapshot()
    snapshot["convertibles"] = [_cla("nocur.md", 100_000, None)]
    result = build_scenarios(snapshot, valuation_date=date(2026, 1, 1))
    assert result["currency"] == "CHF"
    assert result["scenarios"]
    assert any("currency unstated" in a for a in result["assumptions"])


def test_parse_fx_rates() -> None:
    import pytest

    from skills.captable_analysis.captable_analysis import parse_fx_rates

    assert parse_fx_rates(None) == {}
    assert parse_fx_rates(["usd=0.88", "EUR = 0.95"]) == {
        "USD": 0.88, "EUR": 0.95
    }
    with pytest.raises(ValueError):
        parse_fx_rates(["USD"])
    with pytest.raises(ValueError):
        parse_fx_rates(["USD=abc"])
    with pytest.raises(ValueError):
        parse_fx_rates(["USD=-1"])

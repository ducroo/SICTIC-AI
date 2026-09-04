"""Tests for the deterministic conversion/dilution engine.

Anchored on published worked examples (design doc §2.7): the FundersClub
cap+discount example and the Gust pre-money effective-valuation example.
"""

from __future__ import annotations

from datetime import date

import pytest

from lib.captable.model import (
    Note,
    conversion_price,
    convert_in_round,
    loan_balance,
    solve_fixed_point,
    stamp_duty,
    year_fraction,
)

# --- Interest / day counts --------------------------------------------------


def test_year_fraction_conventions() -> None:
    start, end = date(2026, 1, 1), date(2027, 1, 1)
    assert year_fraction(start, end, "act/365") == pytest.approx(1.0)
    assert year_fraction(start, end, "act/360") == pytest.approx(365 / 360)
    assert year_fraction(start, end, "act/act") == pytest.approx(1.0)
    assert year_fraction(start, end, "30/360") == pytest.approx(1.0)


def test_simple_vs_compound_interest() -> None:
    start, end = date(2024, 7, 1), date(2026, 7, 1)
    simple = loan_balance(100_000, 5, start, end, day_count="act/act")
    compound = loan_balance(
        100_000, 5, start, end, day_count="act/act",
        compounding="compound_annual",
    )
    assert simple == pytest.approx(110_000, rel=1e-3)
    assert compound == pytest.approx(110_250, rel=1e-3)  # 1.05^2


# --- Conversion price: FundersClub anchor -----------------------------------


def test_fundersclub_cap_beats_discount() -> None:
    """$25k note, $5M cap, 20% discount; Series A at $10M pre, $5.00/share.

    Cap price = 5M/10M * $5.00 = $2.50 beats the $4.00 discount price;
    the note buys 10,000 shares.
    """
    # $10M pre at $5.00/share implies 2,000,000 pre-round shares.
    result = conversion_price(
        round_price_per_share=5.0,
        denominator_shares=2_000_000,
        cap=5_000_000,
        discount_pct=20,
    )
    assert result.binding_term == "cap"
    assert result.price == pytest.approx(2.50)
    assert 25_000 / result.price == pytest.approx(10_000)


def test_discount_binds_when_cap_is_high() -> None:
    result = conversion_price(
        round_price_per_share=2.0,
        denominator_shares=1_000_000,
        cap=50_000_000,
        discount_pct=20,
    )
    assert result.binding_term == "discount"
    assert result.price == pytest.approx(1.60)


def test_floor_lifts_price_and_nominal_warns() -> None:
    result = conversion_price(
        round_price_per_share=1.0,
        denominator_shares=1_000_000,
        discount_pct=90,
        floor=500_000,
        nominal_value=0.6,
    )
    assert result.binding_term == "floor"
    assert result.price == pytest.approx(0.5)
    assert result.warnings  # 0.5 < nominal 0.6


# --- Three methods ----------------------------------------------------------


def test_gust_pre_money_effective_valuation() -> None:
    """$1M note at 20% discount in a $4M pre round: the discount hands the
    noteholder 1,250,000/PPS-worth of shares, i.e. the note is 'worth'
    $1.25M of the pre-money — the published effective-pre of $2.75M."""
    scenarios = convert_in_round(
        pre_money_valuation=4_000_000,
        new_investment=1_000_000,
        existing_shares={"founders": 1_000_000},
        notes=[Note("note", 1_000_000, discount_pct=20)],
        methods=("pre_money",),
    )
    s = scenarios[0]
    assert s.price_per_share == pytest.approx(4.0)
    # note buys 1,000,000 / 3.20 = 312,500 shares = $1.25M at PPS
    assert s.shares["note"] * s.price_per_share == pytest.approx(1_250_000)


def test_methods_disagree_on_founder_dilution() -> None:
    """Same inputs, different founder outcomes — the reason every scenario
    is computed under all three methods."""
    kwargs = dict(
        pre_money_valuation=8_000_000,
        new_investment=2_000_000,
        existing_shares={"founders": 1_000_000},
        notes=[Note("note", 1_000_000, discount_pct=20)],
    )
    by_method = {
        s.method: s for s in convert_in_round(**kwargs)
    }
    founders = {
        m: s.ownership_pct["founders"] for m, s in by_method.items()
    }
    # pre_money dilutes everyone incl. the new investor; the new investor's
    # slice is protected under percentage_ownership, squeezing founders.
    assert founders["percentage_ownership"] < founders["pre_money"]
    # dollars_invested treats the note as new money: founders keep most.
    assert founders["dollars_invested"] > founders["pre_money"]
    # every scenario's ownership sums to 100
    for s in by_method.values():
        assert sum(s.ownership_pct.values()) == pytest.approx(100.0)


def test_percentage_ownership_holds_investor_share() -> None:
    scenarios = convert_in_round(
        pre_money_valuation=8_000_000,
        new_investment=2_000_000,
        existing_shares={"founders": 1_000_000},
        notes=[Note("note", 500_000, cap=4_000_000, discount_pct=20)],
        methods=("percentage_ownership",),
    )
    s = scenarios[0]
    assert s.ownership_pct["new_investor"] == pytest.approx(20.0, abs=1e-6)


def test_solver_converges() -> None:
    assert solve_fixed_point(lambda x: (x + 2 / x) / 2, 1.0) == pytest.approx(
        2 ** 0.5
    )


# --- Stamp duty -------------------------------------------------------------


def test_stamp_duty_exemption_boundary() -> None:
    assert stamp_duty(0, 900_000) == 0
    assert stamp_duty(900_000, 200_000) == pytest.approx(1_000)
    assert stamp_duty(1_500_000, 100_000) == pytest.approx(1_000)

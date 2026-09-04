"""Deterministic conversion and dilution engine for captable_analysis.

Pure Python, no LLM. Formulas follow the published references cited in the
design doc: SECA conversion-price definition (lower of cap-derived and
discounted round price), Cooley/Gust/Alphabridge for the three market
methods of converting notes in a priced round, and the handbook for Swiss
specifics (stamp duty, nominal floor).

Because a CLA is usually silent on the conversion *method*, every scenario
is computed under all applicable methods and labeled; nothing here ever
picks a method silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# --- Interest ---------------------------------------------------------------


def year_fraction(start: date, end: date, day_count: str) -> float:
    """Accrual year fraction under act/365, act/360, act/act, or 30/360."""
    if end < start:
        raise ValueError("end before start")
    days = (end - start).days
    if day_count == "act/365":
        return days / 365.0
    if day_count == "act/360":
        return days / 360.0
    if day_count == "act/act":
        # ISDA-style: split by calendar year, divide by each year's length.
        fraction = 0.0
        cursor = start
        while cursor < end:
            year_end = date(cursor.year + 1, 1, 1)
            stop = min(end, year_end)
            year_days = (date(cursor.year + 1, 1, 1) - date(cursor.year, 1, 1)).days
            fraction += (stop - cursor).days / year_days
            cursor = stop
        return fraction
    if day_count == "30/360":
        d1, d2 = min(start.day, 30), min(end.day, 30)
        return (
            360 * (end.year - start.year)
            + 30 * (end.month - start.month)
            + (d2 - d1)
        ) / 360.0
    raise ValueError(f"unknown day count {day_count!r}")


def loan_balance(
    principal: float,
    rate_pct: float,
    start: date,
    end: date,
    *,
    day_count: str = "act/365",
    compounding: str = "simple",
) -> float:
    """Principal plus accrued interest at ``end``."""
    if compounding == "simple":
        return principal * (
            1 + rate_pct / 100.0 * year_fraction(start, end, day_count)
        )
    if compounding == "compound_annual":
        balance = principal
        cursor = start
        while cursor < end:
            anniversary = min(
                end, date(cursor.year + 1, cursor.month, cursor.day)
            )
            balance *= 1 + rate_pct / 100.0 * year_fraction(
                cursor, anniversary, day_count
            )
            cursor = anniversary
        return balance
    raise ValueError(f"unknown compounding {compounding!r}")


# --- Conversion price -------------------------------------------------------


@dataclass
class ConversionPriceResult:
    price: float
    binding_term: str  # "cap" | "discount" | "floor"
    warnings: list[str] = field(default_factory=list)


def conversion_price(
    *,
    round_price_per_share: float,
    denominator_shares: float,
    cap: float | None = None,
    discount_pct: float | None = None,
    floor: float | None = None,
    nominal_value: float | None = None,
) -> ConversionPriceResult:
    """SECA-style price: lower of cap-derived and discounted round price,
    but never below a floor-derived price; nominal violations are warned,
    never silently clamped."""
    candidates: list[tuple[float, str]] = []
    if discount_pct is not None:
        candidates.append(
            (round_price_per_share * (1 - discount_pct / 100.0), "discount")
        )
    if cap is not None and denominator_shares:
        candidates.append((cap / denominator_shares, "cap"))
    if not candidates:
        candidates.append((round_price_per_share, "discount"))
    price, binding = min(candidates)
    warnings = []
    if floor is not None and denominator_shares:
        floor_price = floor / denominator_shares
        if price < floor_price:
            price, binding = floor_price, "floor"
    if nominal_value is not None and price < nominal_value:
        warnings.append(
            f"conversion price {price:.4f} below nominal value "
            f"{nominal_value} — legally impossible without split/nominal "
            "reduction (art. 624 CO)"
        )
    return ConversionPriceResult(price, binding, warnings)


# --- Fixed-point solver -----------------------------------------------------


def solve_fixed_point(
    f, x0: float, *, tol: float = 1e-9, max_iterations: int = 200
) -> float:
    """Iterate x = f(x) to convergence (Excel's iterative-calculation
    analogue for the circular conversion/pool arithmetic)."""
    x = x0
    for _ in range(max_iterations):
        nxt = f(x)
        if abs(nxt - x) <= tol * max(1.0, abs(x)):
            return nxt
        x = nxt
    raise ArithmeticError("fixed point iteration did not converge")


# --- Priced-round conversion: the three market methods ----------------------


@dataclass
class Note:
    label: str
    balance: float
    cap: float | None = None
    discount_pct: float | None = None
    floor: float | None = None


@dataclass
class RoundScenario:
    method: str
    price_per_share: float
    shares: dict[str, float]
    ownership_pct: dict[str, float]
    note_prices: dict[str, float]
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def _from_shares(
        method: str,
        price: float,
        shares: dict[str, float],
        note_prices: dict[str, float],
        warnings: list[str],
    ) -> "RoundScenario":
        total = sum(shares.values())
        ownership = {
            holder: 100.0 * count / total for holder, count in shares.items()
        }
        return RoundScenario(method, price, shares, ownership, note_prices, warnings)


def _note_shares(
    notes: list[Note],
    round_price: float,
    denominator_shares: float,
    nominal_value: float | None,
) -> tuple[float, dict[str, float], list[str]]:
    total = 0.0
    prices: dict[str, float] = {}
    warnings: list[str] = []
    for note in notes:
        result = conversion_price(
            round_price_per_share=round_price,
            denominator_shares=denominator_shares,
            cap=note.cap,
            discount_pct=note.discount_pct,
            floor=note.floor,
            nominal_value=nominal_value,
        )
        prices[note.label] = result.price
        warnings += [f"{note.label}: {w}" for w in result.warnings]
        total += note.balance / result.price
    return total, prices, warnings


def convert_in_round(
    *,
    pre_money_valuation: float,
    new_investment: float,
    existing_shares: dict[str, float],
    notes: list[Note],
    nominal_value: float | None = None,
    methods: tuple[str, ...] = (
        "pre_money",
        "percentage_ownership",
        "dollars_invested",
    ),
) -> list[RoundScenario]:
    """Convert notes in a priced round under each requested method.

    ``existing_shares`` maps holder -> pre-round fully-diluted shares (the
    denominator basis the CLA prescribes is the caller's responsibility).
    Duplicate note labels are uniquified so per-note prices never collapse.
    """
    seen: dict[str, int] = {}
    uniquified = []
    for note in notes:
        count = seen.get(note.label, 0)
        seen[note.label] = count + 1
        if count:
            note = Note(
                label=f"{note.label} #{count + 1}",
                balance=note.balance,
                cap=note.cap,
                discount_pct=note.discount_pct,
                floor=note.floor,
            )
        uniquified.append(note)
    notes = uniquified
    fd_pre = sum(existing_shares.values())
    scenarios = []
    for method in methods:
        if method == "pre_money":
            # PPS fixed by pre-money / pre-round FD; note shares dilute
            # everyone, new investor included.
            price = pre_money_valuation / fd_pre
            note_total, note_prices, warnings = _note_shares(
                notes, price, fd_pre, nominal_value
            )
            investor_shares = new_investment / price
        elif method == "percentage_ownership":
            # Investor's post-round percentage is fixed at
            # investment / (pre + investment); solve the circular price.
            target_pct = new_investment / (
                pre_money_valuation + new_investment
            )

            def iterate(price: float) -> float:
                note_total, _, _ = _note_shares(
                    notes, price, fd_pre, nominal_value
                )
                # investor_shares = target_pct * total_post
                # total_post = (fd_pre + note_total) / (1 - target_pct)
                total_post = (fd_pre + note_total) / (1 - target_pct)
                investor = target_pct * total_post
                return new_investment / investor

            price = solve_fixed_point(iterate, pre_money_valuation / fd_pre)
            note_total, note_prices, warnings = _note_shares(
                notes, price, fd_pre, nominal_value
            )
            investor_shares = new_investment / price
        elif method == "dollars_invested":
            # Note balances count as newly invested dollars: the effective
            # pre-money for pricing includes them, so only the discount's
            # extra shares dilute the founders.
            balances = sum(note.balance for note in notes)
            price = (pre_money_valuation + balances) / fd_pre
            note_total, note_prices, warnings = _note_shares(
                notes, price, fd_pre, nominal_value
            )
            investor_shares = new_investment / price
        else:
            raise ValueError(f"unknown method {method!r}")

        shares = dict(existing_shares)
        for note in notes:
            shares[note.label] = (
                shares.get(note.label, 0.0)
                + note.balance / note_prices[note.label]
            )
        shares["new_investor"] = (
            shares.get("new_investor", 0.0) + investor_shares
        )
        scenarios.append(
            RoundScenario._from_shares(
                method, price, shares, note_prices, warnings
            )
        )
    return scenarios


# --- Swiss stamp duty -------------------------------------------------------

STAMP_DUTY_EXEMPTION_CHF = 1_000_000.0
STAMP_DUTY_RATE = 0.01


def stamp_duty(
    cumulative_paid_in_before: float, new_contribution: float
) -> float:
    """1% issuance stamp duty on contributions above the CHF 1M lifetime
    exemption (nominal + agio)."""
    taxable_before = max(
        0.0, cumulative_paid_in_before - STAMP_DUTY_EXEMPTION_CHF
    )
    taxable_after = max(
        0.0,
        cumulative_paid_in_before
        + new_contribution
        - STAMP_DUTY_EXEMPTION_CHF,
    )
    return STAMP_DUTY_RATE * (taxable_after - taxable_before)

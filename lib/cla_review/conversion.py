"""The member's conversion of a CLA term sheet on the consolidated cap table.

Design step 5 of docs/cla-review-design.md. Pure arithmetic over the term
sheet extraction, a consolidated ``captable_build`` snapshot and the
``cla_review`` settings, through ``lib.captable.model`` and
``lib.captable.notes``. Every input is resolved and labelled first
(evidenced, explicit or assumption); a calculation whose essential input is
missing is omitted with its reason, never computed on an invented value.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from lib.captable.assessment import _value as extraction_value
from lib.captable.model import Note, conversion_price, convert_in_round, loan_balance, stamp_duty
from lib.captable.notes import existing_shares, normalize_currency, notes_from_snapshot, notes_in_currency

EVIDENCED = "evidenced"
EXPLICIT = "explicit"
ASSUMPTION = "assumption"
MY_TICKET = "my ticket"
OTHER_NEW_LENDERS = "other new lenders (assumed)"


def _input(value: Any, source: str, note: str | None = None) -> dict[str, Any]:
    return {"value": value, "source": source, "note": note}


def _setting(settings: dict[str, Any], name: str) -> Any:
    return settings["rules"][name]["value"]


def _parse_iso(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _issued_shares(snapshot: dict[str, Any]) -> float:
    return sum(
        holding.get("count") or 0.0
        for holder in snapshot.get("stakeholders", [])
        if holder.get("kind") not in ("treasury", "pool", "authorized_capital")
        for holding in holder.get("holdings", [])
    )


def resolve_inputs(
    term_sheet: dict[str, Any],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    ticket: float | None,
    as_of: date,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]], list[str]]:
    """Return (inputs, omitted calculations, assumptions) before any number is computed."""
    v = lambda field: extraction_value(term_sheet, field)  # noqa: E731
    inputs: dict[str, dict[str, Any]] = {}
    omitted: list[dict[str, str]] = []
    assumptions: list[str] = []

    currency = normalize_currency(v("principal_currency"))
    inputs["currency"] = _input(currency or "CHF", EVIDENCED if currency else ASSUMPTION,
                                None if currency else "the term sheet states no currency; CHF assumed")

    aggregate = v("aggregate_amount_max")
    aggregate_field = "aggregate_amount_max"
    if aggregate is None:
        aggregate, aggregate_field = v("aggregate_amount_min"), "aggregate_amount_min"
    inputs["aggregate_round_amount"] = _input(
        aggregate, EVIDENCED if aggregate is not None else ASSUMPTION,
        f"from {aggregate_field}" if aggregate is not None else "the term sheet states no aggregate amount",
    )

    member_count = int(_setting(settings, "member_count_n"))
    inputs["member_count_n"] = _input(member_count, ASSUMPTION, "configured syndicate size, settings.json")
    if ticket is not None:
        inputs["ticket"] = _input(float(ticket), EXPLICIT, "given on the command line")
    elif aggregate is not None:
        inputs["ticket"] = _input(
            round(float(aggregate) / member_count, 2), ASSUMPTION,
            f"the aggregate {aggregate:,.0f} divided by the configured member count {member_count}; "
            "not a per-member minimum stated by the document",
        )
    else:
        inputs["ticket"] = _input(None, ASSUMPTION, "no ticket given and no aggregate amount to derive one from")
        omitted.append({"calculation": "my conversion", "reason": "no ticket: give --ticket or a term sheet with an aggregate amount"})

    my_ticket = inputs["ticket"]["value"]
    if aggregate is not None and my_ticket is not None:
        others = max(0.0, float(aggregate) - float(my_ticket))
        inputs["other_new_lenders"] = _input(others, ASSUMPTION, "the round fills to the aggregate amount; the rest is lent by others")
    else:
        inputs["other_new_lenders"] = _input(None, ASSUMPTION, "unknown without an aggregate amount; not modelled")

    new_money, raise_threshold = v("qefr_min_new_money"), v("qefr_min_raise")
    round_investment = new_money if new_money is not None else raise_threshold
    inputs["round_investment"] = _input(
        float(round_investment) if round_investment is not None else None,
        ASSUMPTION,
        "the qualified-financing minimum of NEW money taken as the size of the next round" if new_money is not None
        else ("the qualified-financing threshold taken as the size of the next round; if that threshold counts the "
              "converting loans, new money is smaller and the new investor's share and the stamp duty are overstated")
        if raise_threshold is not None else "no qualified-financing threshold stated",
    )
    if round_investment is None:
        omitted.append({"calculation": "my conversion", "reason": "no round size: the term sheet states no qualified-financing threshold"})

    maturity = _parse_iso(v("maturity_date"))
    inputs["conversion_dates"] = _input(
        [str(as_of)] + ([str(maturity)] if maturity else []),
        EVIDENCED if maturity else ASSUMPTION,
        "the run date (no accrued interest) and the maturity date (maximum accrual)" if maturity
        else "the run date only; the term sheet states no parseable maturity date",
    )

    rate = v("interest_rate_pct") or 0.0
    day_count = v("interest_day_count")
    if day_count in (None, "unstated"):
        day_count = "act/365"
        assumptions.append("term sheet: day count unstated; act/365 assumed.")
    compounding = v("interest_compounding")
    if compounding in (None, "unstated"):
        compounding = "simple"
        assumptions.append("term sheet: compounding unstated; simple assumed.")
    inputs["interest"] = _input({"rate_pct": rate, "day_count": day_count, "compounding": compounding},
                                EVIDENCED if v("interest_rate_pct") is not None else ASSUMPTION,
                                None if v("interest_rate_pct") is not None else "no interest rate stated; 0% assumed")

    basis = v("denominator_basis")
    fully_diluted = existing_shares(snapshot)
    if basis == "issued_and_outstanding":
        denominator = _issued_shares(snapshot)
        inputs["denominator"] = _input({"basis": basis, "shares": denominator}, EVIDENCED, "issued and outstanding shares of the snapshot")
    else:
        denominator = sum(fully_diluted.values())
        inputs["denominator"] = _input(
            {"basis": "fully_diluted", "shares": denominator},
            EVIDENCED if basis == "fully_diluted" else ASSUMPTION,
            None if basis == "fully_diluted" else "denominator basis unstated; pre-round fully diluted shares assumed",
        )
    if not denominator:
        omitted.append({"calculation": "my conversion", "reason": "the snapshot has no share count to price the conversion on"})

    nominal_values = [c.get("nominal_value") for c in snapshot.get("share_classes", []) if c.get("nominal_value")]
    inputs["nominal_value"] = _input(min(nominal_values) if nominal_values else None,
                                     EVIDENCED if nominal_values else ASSUMPTION,
                                     None if nominal_values else "no nominal value in the snapshot; the art. 624 CO floor is not checked")

    cap, discount, floor = v("valuation_cap"), v("discount_pct"), v("valuation_floor")
    inputs["cap_discount_floor"] = _input({"cap": cap, "discount_pct": discount, "floor": floor}, EVIDENCED)
    if cap is not None:
        grid = [round(float(cap) * float(m), 2) for m in _setting(settings, "valuation_grid_multiples_of_cap")]
        inputs["valuation_grid"] = _input(grid, ASSUMPTION, "multiples of the valuation cap, settings.json")
    elif _setting(settings, "valuation_grid_absolute"):
        grid = [float(x) for x in _setting(settings, "valuation_grid_absolute")]
        inputs["valuation_grid"] = _input(grid, ASSUMPTION, "explicit grid for an uncapped term sheet, settings.json")
    else:
        inputs["valuation_grid"] = _input(None, ASSUMPTION, "uncapped term sheet and no explicit valuation grid configured")
        omitted.append({"calculation": "my conversion", "reason": "uncapped term sheet: set valuation_grid_absolute in settings.json"})

    inputs["round_method"] = _input(_setting(settings, "conversion_round_method"), ASSUMPTION, "settings.json; captable shows all three methods")
    return inputs, omitted, assumptions


def my_conversion(
    term_sheet: dict[str, Any],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    ticket: float | None,
    as_of: date,
) -> dict[str, Any]:
    inputs, omitted, assumptions = resolve_inputs(term_sheet, snapshot, settings, ticket=ticket, as_of=as_of)
    result: dict[str, Any] = {
        "as_of": str(as_of), "inputs": inputs, "assumptions": assumptions, "omitted": omitted,
        "balances": {}, "crossover_valuation": None, "scenarios": [], "stamp_duty": None,
    }
    terms = inputs["cap_discount_floor"]["value"]
    if terms["cap"] is not None and terms["discount_pct"] is not None and terms["discount_pct"] < 100:
        result["crossover_valuation"] = round(float(terms["cap"]) / (1 - float(terms["discount_pct"]) / 100.0), 2)
    if any(item["calculation"] == "my conversion" for item in omitted):
        return result

    currency = inputs["currency"]["value"]
    my_ticket = float(inputs["ticket"]["value"])
    others = inputs["other_new_lenders"]["value"]
    round_investment = float(inputs["round_investment"]["value"])
    interest = inputs["interest"]["value"]
    denominator = inputs["denominator"]["value"]["shares"]
    issued_basis = inputs["denominator"]["value"]["basis"] == "issued_and_outstanding"
    nominal = inputs["nominal_value"]["value"]
    existing = existing_shares(snapshot)
    method = inputs["round_method"]["value"]

    def balance(principal: float, at: date) -> float:
        return loan_balance(principal, float(interest["rate_pct"]), as_of, at,
                            day_count=interest["day_count"],
                            compounding="compound_annual" if str(interest["compounding"]).startswith("compound") else "simple")

    for label in inputs["conversion_dates"]["value"]:
        at = date.fromisoformat(label)
        result["balances"][label] = round(balance(my_ticket, at), 2)
        existing_notes, note_assumptions = notes_from_snapshot(snapshot, at)
        converted, unconverted, fx_assumptions = notes_in_currency(existing_notes, currency, {})
        for text in note_assumptions + fx_assumptions:
            if text not in assumptions:
                assumptions.append(text)
        if unconverted:
            result["omitted"].append({
                "calculation": f"my conversion at {label}",
                "reason": "existing loans in another currency without an FX rate: "
                          + ", ".join(f"{n.label} ({n.currency})" for n in unconverted),
            })
            continue
        my_note = Note(label=MY_TICKET, balance=balance(my_ticket, at), cap=terms["cap"], discount_pct=terms["discount_pct"],
                       floor=terms["floor"], currency=currency, denominator_shares=denominator if issued_basis else None)
        notes = list(converted) + [my_note]
        if others:
            notes.append(Note(label=OTHER_NEW_LENDERS, balance=balance(float(others), at), cap=terms["cap"],
                              discount_pct=terms["discount_pct"], floor=terms["floor"], currency=currency,
                              denominator_shares=denominator if issued_basis else None))
        for pre_money in inputs["valuation_grid"]["value"]:
            [scenario] = convert_in_round(
                pre_money_valuation=pre_money, new_investment=round_investment, existing_shares=existing,
                notes=notes, nominal_value=nominal, methods=(method,),
            )
            priced = conversion_price(
                round_price_per_share=scenario.price_per_share, denominator_shares=denominator,
                cap=terms["cap"], discount_pct=terms["discount_pct"], floor=terms["floor"], nominal_value=nominal,
            )
            existing_loans_pct = sum(pct for holder, pct in scenario.ownership_pct.items() if holder.startswith("lenders of "))
            result["scenarios"].append({
                "conversion_date": label,
                "pre_money": pre_money,
                "round_price": round(scenario.price_per_share, 4),
                "my_price": round(scenario.note_prices[MY_TICKET], 4),
                "binding_term": priced.binding_term,
                "my_shares": round(scenario.shares[MY_TICKET], 2),
                "my_ownership_pct": round(scenario.ownership_pct[MY_TICKET], 4),
                "other_new_lenders_ownership_pct": round(scenario.ownership_pct.get(OTHER_NEW_LENDERS, 0.0), 4),
                "existing_loans_ownership_pct": round(existing_loans_pct, 4),
                "new_investor_ownership_pct": round(scenario.ownership_pct["new_investor"], 4),
                "warnings": list(scenario.warnings),
            })

    if currency == "CHF":
        paid_in = sum(s.get("invested_amount") or 0.0 for s in snapshot.get("stakeholders", []))
        existing_notes, _ = notes_from_snapshot(snapshot, as_of)
        converting = sum(n.balance for n in existing_notes if n.currency in (None, "CHF")) + my_ticket + float(others or 0.0)
        result["stamp_duty"] = {
            "cumulative_paid_in_before": round(paid_in, 2),
            "round_contribution": round(round_investment + converting, 2),
            "duty": round(stamp_duty(paid_in, round_investment + converting), 2),
            "note": "1% issuance stamp duty above the CHF 1M lifetime exemption on the new money plus every converting balance "
                    "at the run date; the company pays it, so it dilutes nobody but reduces the proceeds",
        }
    else:
        result["omitted"].append({"calculation": "stamp duty", "reason": f"only computed for CHF; the term sheet is in {currency}"})
    return result

"""Convertible notes and share counts read from a consolidated captable_build snapshot.

Shared by the ``captable`` report and ``cla_review``: which executed loans
convert, with what accrued balance, cap, discount, floor and denominator, and
which holders dilute. Every default applied along the way is returned as an
assumption string, never silently.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from lib.captable.data import field_value, parse_extraction_date
from lib.captable.model import Note, loan_balance

NOTE_LABEL_PREFIX = "lenders of "


def note_label(document: Any) -> str:
    """The holder label under which an executed loan's lenders appear in a scenario."""
    return f"{NOTE_LABEL_PREFIX}{document}"


def existing_shares(snapshot: dict[str, Any]) -> dict[str, float]:
    """Pre-round fully-diluted shares per holder (treasury excluded).

    Pool/reserved positions still dilute, but they are not shareholders —
    label them so scenario ownership tables don't list them beside people.
    """
    shares: dict[str, float] = {}
    for stakeholder in snapshot.get("stakeholders", []):
        if stakeholder.get("kind") == "treasury":
            continue
        diluted = stakeholder.get("diluted_count")
        if diluted is None:
            diluted = sum(
                h.get("count") or 0.0
                for h in stakeholder.get("holdings", [])
            )
        if diluted:
            name = stakeholder.get("name", "unknown")
            if stakeholder.get("kind") in ("pool", "authorized_capital"):
                name = f"[reserved pool] {name}"
            shares[name] = diluted
    return shares


def issued_shares(snapshot: dict[str, Any]) -> float:
    """Issued and outstanding shares: every holding except treasury, pools and authorized capital."""
    return sum(
        holding.get("count") or 0.0
        for holder in snapshot.get("stakeholders", [])
        if holder.get("kind") not in ("treasury", "pool", "authorized_capital")
        for holding in holder.get("holdings", [])
    )


def normalize_currency(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


def notes_in_currency(
    notes: list[Note], target: str, fx_rates: dict[str, float]
) -> tuple[list[Note], list[Note], list[str]]:
    """Express every note in ``target``; notes without a rate are set aside.

    Balances, caps and floors are money amounts in the loan currency, so
    all three convert at the same rate. Mixing currencies without
    conversion would misstate dilution, so unconvertible notes are never
    silently summed with the rest.
    """
    converted: list[Note] = []
    unconverted: list[Note] = []
    assumptions: list[str] = []
    for note in notes:
        if note.currency is None:
            assumptions.append(
                f"{note.label}: loan currency unstated; {target} assumed."
            )
            converted.append(note)
        elif note.currency == target:
            converted.append(note)
        elif note.currency in fx_rates:
            rate = fx_rates[note.currency]
            converted.append(
                Note(
                    label=note.label,
                    balance=note.balance * rate,
                    cap=note.cap * rate if note.cap else note.cap,
                    discount_pct=note.discount_pct,
                    floor=note.floor * rate if note.floor else note.floor,
                    currency=target,
                    denominator_shares=note.denominator_shares,
                )
            )
            assumptions.append(
                f"{note.label}: {note.currency} balance, cap and floor "
                f"converted to {target} at the supplied rate "
                f"{rate} {target} per 1 {note.currency}."
            )
        else:
            unconverted.append(note)
    return converted, unconverted, assumptions


def notes_from_snapshot(
    snapshot: dict[str, Any], valuation_date: date
) -> tuple[list[Note], list[str]]:
    notes: list[Note] = []
    assumptions: list[str] = []
    for cla in snapshot.get("convertibles", []):
        if cla.get("status") != "executed":
            continue
        principal = field_value(cla.get("principal_total"))
        if not principal:
            assumptions.append(f"{cla.get('document')}: principal unstated; the loan is left out of the converting stack.")
            continue
        rate = field_value(cla.get("interest_rate_pct")) or 0.0
        if field_value(cla.get("interest_mode")) == "safe_harbor_capped":
            safe_harbor = field_value(cla.get("interest_safe_harbor_rate_pct"))
            if safe_harbor is not None and safe_harbor < rate:
                assumptions.append(
                    f"{cla.get('document')}: interest is the LOWER of the "
                    f"stated {rate}% and the tax safe-harbor rate; computed "
                    f"with the document's safe-harbor figure ({safe_harbor}%)."
                    " The safe-harbor rate is set yearly — verify the "
                    "currently applicable ESTV rate."
                )
                rate = safe_harbor
            elif safe_harbor is None:
                assumptions.append(
                    f"{cla.get('document')}: interest is capped at the tax "
                    f"safe-harbor rate, which the document does not quantify;"
                    f" computed with the stated {rate}% ceiling, which likely"
                    " OVERSTATES the balance — obtain the applicable ESTV "
                    "safe-harbor rate."
                )
        day_count = field_value(cla.get("interest_day_count"))
        if day_count in (None, "unstated"):
            day_count = "act/365"
            assumptions.append(
                f"{cla.get('document')}: day count unstated; act/365 assumed."
            )
        compounding = field_value(cla.get("interest_compounding"))
        if compounding in (None, "unstated"):
            compounding = "simple"
            assumptions.append(
                f"{cla.get('document')}: compounding unstated; simple assumed."
            )
        elif compounding == "compound_other":
            assumptions.append(
                f"{cla.get('document')}: non-annual compounding stated; "
                "computed as ANNUAL compounding (approximation, slightly "
                "understates the balance)."
            )
        start = parse_extraction_date(field_value(cla.get("execution_date")))
        if start is None:
            start = valuation_date
            assumptions.append(
                f"{cla.get('document')}: execution date unparseable; "
                "no interest accrued in the scenarios."
            )
        elif start > valuation_date:
            start = valuation_date
            assumptions.append(
                f"{cla.get('document')}: execution date "
                f"{field_value(cla.get('execution_date'))!r} lies after the "
                "valuation date (typo/OCR?); no interest accrued."
            )
        balance = loan_balance(
            float(principal),
            float(rate),
            start,
            valuation_date,
            day_count=day_count,
            compounding="compound_annual"
            if str(compounding).startswith("compound")
            else "simple",
        )
        basis = field_value(cla.get("denominator_basis"))
        denominator = None
        if basis == "issued_and_outstanding":
            denominator = issued_shares(snapshot)
            if denominator <= 0:
                raise ValueError(f"{cla.get('document')}: no issued and outstanding shares for conversion.")
        elif basis not in (None, "unstated", "fully_diluted"):
            raise ValueError(f"Unsupported conversion denominator: {basis!r}")
        elif basis in (None, "unstated") and (
            field_value(cla.get("valuation_cap")) or field_value(cla.get("valuation_floor"))
        ):
            assumptions.append(f"{cla.get('document')}: cap/floor denominator unstated; pre-round fully diluted shares assumed.")
        notes.append(
            Note(
                label=note_label(cla.get("document")),
                balance=balance,
                cap=field_value(cla.get("valuation_cap")),
                discount_pct=field_value(cla.get("discount_pct")),
                floor=field_value(cla.get("valuation_floor")),
                denominator_shares=denominator,
                currency=normalize_currency(
                    field_value(cla.get("principal_currency"))
                    or field_value(cla.get("currency"))
                ),
            )
        )
    return notes, assumptions

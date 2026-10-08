"""The existing loans next to a CLA term sheet (design step 6).

Pure functions over the term sheet extraction and the executed convertibles
of a consolidated ``captable_build`` snapshot: terms side by side, the
most-favoured-nation reading in both directions, identical-terms group
membership, and the 10/20 non-bank counts before and after N syndicate
members join on these terms. Counting reuses ``aggregate_clas``; the
"after" state is a synthetic executed copy of the term sheet.
"""
from __future__ import annotations

import copy
from datetime import date
from typing import Any

from lib.captable.aggregation import aggregate_clas, terms_group_key
from lib.captable.data import extraction_value, parse_extraction_date

SCENARIO_MEMBER = "Syndicate member {index} (scenario)"
COMPARED_TERMS = (
    "principal_total", "principal_currency", "valuation_cap", "discount_pct", "valuation_floor",
    "denominator_basis", "maturity_date", "interest_mode", "interest_rate_pct", "subordinated",
    "subordination_scope", "mfn_clause", "pro_rata_rights", "qefr_min_raise",
)


def _row(extraction: dict[str, Any], role: str) -> dict[str, Any]:
    row = {"document": extraction.get("document"), "role": role,
           "lenders": [lender.get("name") for lender in extraction.get("lenders") or []]}
    for field in COMPARED_TERMS:
        row[field] = extraction_value(extraction, field)
    return row


def _more_favourable_to_lender(candidate: dict[str, Any], other: dict[str, Any]) -> list[str]:
    """Terms of ``candidate`` a lender would prefer over ``other``'s."""
    v = lambda x, f: extraction_value(x, f)  # noqa: E731
    better: list[str] = []
    if v(candidate, "valuation_cap") is not None and (v(other, "valuation_cap") is None or v(candidate, "valuation_cap") < v(other, "valuation_cap")):
        better.append("lower valuation cap" if v(other, "valuation_cap") is not None else "a valuation cap where the other has none")
    if (v(candidate, "discount_pct") or 0) > (v(other, "discount_pct") or 0):
        better.append("higher discount")
    if (v(candidate, "interest_rate_pct") or 0) > (v(other, "interest_rate_pct") or 0):
        better.append("higher interest")
    if v(candidate, "valuation_floor") is None and v(other, "valuation_floor") is not None:
        better.append("no valuation floor")
    return better


def loan_context(
    term_sheet: dict[str, Any],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    ticket: float | None,
    as_of: date,
) -> dict[str, Any]:
    executed = [c for c in snapshot.get("convertibles", []) if c.get("status") == "executed"]
    comparison = [_row(term_sheet, "term sheet under review")] + [_row(c, "executed loan") for c in executed]

    mfn = {
        "term_sheet_has_mfn": bool(extraction_value(term_sheet, "mfn_clause")),
        "existing_loans_with_mfn": [c["document"] for c in executed if extraction_value(c, "mfn_clause")],
        "term_sheet_more_favourable_than": [
            {"document": c["document"], "terms": terms}
            for c in executed if (terms := _more_favourable_to_lender(term_sheet, c))
        ],
        "existing_more_favourable_than_term_sheet": [
            {"document": c["document"], "terms": terms}
            for c in executed if (terms := _more_favourable_to_lender(c, term_sheet))
        ],
    }
    readings: list[str] = []
    for entry in mfn["term_sheet_more_favourable_than"]:
        if entry["document"] in mfn["existing_loans_with_mfn"]:
            readings.append(f"{entry['document']} has an MFN clause and the term sheet offers {', '.join(entry['terms'])}: "
                            "those terms would flow to that lender too, enlarging the converting stack.")
    for entry in mfn["existing_more_favourable_than_term_sheet"]:
        if mfn["term_sheet_has_mfn"]:
            readings.append(f"The term sheet's MFN clause would pull in {', '.join(entry['terms'])} from {entry['document']}.")
        else:
            readings.append(f"{entry['document']} has {', '.join(entry['terms'])} and the term sheet has no MFN clause: "
                            "the member would lend on worse terms than an existing lender.")
    if not readings:
        readings.append("No most-favoured-nation effect in either direction.")
    mfn["readings"] = readings

    key = terms_group_key(term_sheet)
    identical = [c["document"] for c in executed if terms_group_key(c) == key]
    identical_terms = {"joins_existing_group": bool(identical), "documents": identical}

    member_count = int(settings["rules"]["member_count_n"]["value"])
    lenders = [dict(lender) for lender in term_sheet.get("lenders") or []]
    named = {(lender.get("name") or "").strip().casefold() for lender in lenders}
    synthetic = copy.deepcopy(term_sheet)
    synthetic["document"] = f"{term_sheet.get('document')} (scenario: executed with {member_count} members)"
    synthetic["status"] = "executed"
    synthetic["execution_date"] = {"value": str(as_of), "quote": None}
    synthetic["lenders"] = lenders + [
        {"name": SCENARIO_MEMBER.format(index=index), "kind": "individual", "domicile": "CH",
         "principal_amount": float(ticket) if ticket is not None else None, "quote": "scenario"}
        for index in range(1, member_count + 1)
        if SCENARIO_MEMBER.format(index=index).casefold() not in named
    ]
    synthetic["principal_total"] = {"value": None, "quote": None}
    before = aggregate_clas(executed, run_date=as_of)
    after = aggregate_clas(executed + [synthetic], run_date=as_of)
    group_after = next(
        (g["lender_count"] for g in after["identical_terms_groups"] if synthetic["document"] in g["documents"]), None,
    )
    ten_twenty = {
        "member_count_n": member_count,
        "before": before["ten_twenty_rule"],
        "after": after["ten_twenty_rule"],
        "term_sheet_group_lenders_after": group_after,
        "note": "The 10 rule counts lenders on identical terms, the 20 rule every non-bank lender; a syndicate or nominee "
                "counts its sub-participants (Handbook 8.4). Scenario members are named so they never match a real lender.",
    }

    maturities = sorted(
        [{"document": row["document"], "maturity_date": row["maturity_date"], "role": row["role"]} for row in comparison],
        key=lambda item: (parse_extraction_date(item["maturity_date"]) is None, parse_extraction_date(item["maturity_date"]) or date.min, str(item["maturity_date"])),
    )
    return {
        "as_of": str(as_of),
        "executed_count": len(executed),
        "comparison": comparison,
        "mfn": mfn,
        "identical_terms": identical_terms,
        "ten_twenty": ten_twenty,
        "maturities": maturities,
    }

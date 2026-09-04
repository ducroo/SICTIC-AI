"""Stage 4: aggregate the extracted CLAs of one dataset. Pure Python.

Semantics (design doc §2.1 stage 4 + 2026-09-04 review):

- "Identical terms" is a tuple over the economic terms, not "same document":
  Swiss CLA rounds are commonly issued as separate per-lender agreements on
  identical conditions, and the 10 non-bank rule counts lenders per
  identical-terms group while the 20 rule counts lenders across varying
  terms.
- A lender appearing in several loans counts once for the 10/20 rules but
  each loan counts toward outstanding principal.
- A term sheet is superseded by any executed CLA of the same lender; it is
  never summed, but an amount discrepancy becomes a diligence question.
- Only ``executed`` loans count as outstanding. Expired maturities without
  conversion evidence are reported as "expired — check for conversion
  documents", never silently treated as outstanding-and-fine.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

_SEVERITY_ORDER = ("info", "medium", "high", "severe")


def _value(entry: Any) -> Any:
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def normalize_lender_name(name: str) -> str:
    """Collapse spelling variants of the same lender name."""
    cleaned = re.sub(r"[^\w\s]", " ", name.casefold())
    return " ".join(cleaned.split())


def names_match(a: str, b: str) -> bool:
    """Same person/entity despite middle names or extra legal-form tokens.

    True when the tokens of one normalized name are a subset of the other's
    ("anna beispiel" vs "anna barbara beispiel"), requiring at least two shared tokens
    (or exact equality for single-token names) to avoid false positives.
    """
    tokens_a = set(normalize_lender_name(a).split())
    tokens_b = set(normalize_lender_name(b).split())
    if not tokens_a or not tokens_b:
        return False
    if tokens_a == tokens_b:
        return True
    smaller, larger = sorted((tokens_a, tokens_b), key=len)
    return len(smaller) >= 2 and smaller <= larger


def terms_group_key(extraction: dict[str, Any]) -> tuple:
    """The identical-terms tuple used for 10/20 non-bank grouping."""
    return (
        _value(extraction.get("interest_mode")),
        _value(extraction.get("interest_rate_pct")),
        _value(extraction.get("discount_pct")),
        _value(extraction.get("valuation_cap")),
        _value(extraction.get("valuation_floor")),
        _value(extraction.get("maturity_date")),
        _value(extraction.get("qefr_min_raise")),
        _value(extraction.get("principal_currency")),
    )


def _loan_amounts(extraction: dict[str, Any]) -> list[tuple[str, float | None]]:
    """(lender name, amount) pairs for one agreement."""
    lenders = extraction.get("lenders") or []
    total = _value(extraction.get("principal_total"))
    if len(lenders) == 1:
        name = lenders[0].get("name", "unknown")
        amount = lenders[0].get("principal_amount")
        return [(name, amount if amount is not None else total)]
    pairs = []
    for lender in lenders:
        pairs.append((lender.get("name", "unknown"), lender.get("principal_amount")))
    return pairs


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    from lib.captable.snapshot import normalize_iso_date

    value = normalize_iso_date(value)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def aggregate_clas(
    extractions: list[dict[str, Any]],
    *,
    run_date: date | None = None,
    conversion_window_days: int = 30,
    esign_markers: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Aggregate all extracted CLA documents of one dataset."""
    run_date = run_date or date.today()
    esign_markers = esign_markers or {}
    executed = [e for e in extractions if e.get("status") == "executed"]
    term_sheets = [e for e in extractions if e.get("status") == "term_sheet"]
    settled = [
        e for e in extractions if e.get("status") in ("converted", "repaid")
    ]
    diligence_questions: list[str] = []
    caveats: list[str] = []

    # --- Term-sheet supersession and discrepancies ------------------------
    executed_by_lender: dict[str, list[dict]] = {}
    for extraction in executed:
        for name, _amount in _loan_amounts(extraction):
            executed_by_lender.setdefault(
                normalize_lender_name(name), []
            ).append(extraction)

    superseded_term_sheets = []
    open_term_sheets = []
    for sheet in term_sheets:
        sheet_lenders = {
            normalize_lender_name(name) for name, _ in _loan_amounts(sheet)
        }
        matching = sheet_lenders & set(executed_by_lender)
        if matching:
            superseded_term_sheets.append(sheet["document"])
            sheet_amount = _value(sheet.get("principal_total"))
            for lender_key in matching:
                executed_amount = sum(
                    amount
                    for e in executed_by_lender[lender_key]
                    for name, amount in _loan_amounts(e)
                    if normalize_lender_name(name) == lender_key
                    and amount is not None
                )
                if (
                    sheet_amount is not None
                    and abs(executed_amount - sheet_amount) > 0.01
                ):
                    diligence_questions.append(
                        f"Term sheet {sheet['document']!r} contemplates "
                        f"{sheet_amount:,.0f} but executed loans of the same "
                        f"lender total {executed_amount:,.0f} — clarify the "
                        "difference."
                    )
        else:
            open_term_sheets.append(sheet["document"])
            diligence_questions.append(
                f"Term sheet {sheet['document']!r} has no matching executed "
                "CLA in the data room — was the loan ever concluded?"
            )

    # --- Identical-terms grouping (10/20 non-bank rules) ------------------
    groups: dict[tuple, dict[str, Any]] = {}
    for extraction in executed:
        key = terms_group_key(extraction)
        group = groups.setdefault(
            key,
            {"documents": [], "lenders": set(), "total_principal": 0.0,
             "unknown_amounts": 0},
        )
        group["documents"].append(extraction["document"])
        for name, amount in _loan_amounts(extraction):
            group["lenders"].add(normalize_lender_name(name))
            if amount is None:
                group["unknown_amounts"] += 1
            else:
                group["total_principal"] += amount

    all_lenders: set[str] = set()
    syndicate_present = False
    for extraction in executed:
        for lender in extraction.get("lenders") or []:
            all_lenders.add(normalize_lender_name(lender.get("name", "")))
            if lender.get("kind") in ("syndicate", "nominee"):
                syndicate_present = True
    if syndicate_present:
        caveats.append(
            "A syndicate/nominee lender is present; sub-participants count "
            "toward the 10/20 non-bank limits but their number is "
            "undisclosed — lender counts are lower bounds."
        )

    max_identical_group = max(
        (len(g["lenders"]) for g in groups.values()), default=0
    )
    ten_twenty = {
        "max_lenders_on_identical_terms": max_identical_group,
        "total_lenders_all_terms": len(all_lenders),
        "ten_rule": "exceeded" if max_identical_group > 10 else "within",
        "twenty_rule": "exceeded" if len(all_lenders) > 20 else "within",
        "caveats": caveats,
    }
    if max_identical_group > 10 or len(all_lenders) > 20:
        diligence_questions.append(
            "Non-bank lender count near/over the 10/20 thresholds — verify "
            "withholding-tax treatment of interest with tax counsel."
        )

    # --- Outstanding principal + maturity status --------------------------
    outstanding_total = 0.0
    unknown_amounts = 0
    maturity_findings = []
    for extraction in executed:
        for _name, amount in _loan_amounts(extraction):
            if amount is None:
                unknown_amounts += 1
            else:
                outstanding_total += amount
        maturity = _parse_date(_value(extraction.get("maturity_date")))
        if maturity is not None:
            deadline = maturity + timedelta(days=conversion_window_days)
            if deadline < run_date:
                maturity_findings.append(
                    {
                        "document": extraction["document"],
                        "maturity_date": str(maturity),
                        "status": "expired_check_for_conversion",
                        "detail": (
                            f"Maturity {maturity} and the "
                            f"{conversion_window_days}-day conversion window "
                            "have passed; no conversion/repayment evidence "
                            "in the data room. Request conversion notices, "
                            "extension agreements, or repayment records."
                        ),
                    }
                )
            else:
                maturity_findings.append(
                    {
                        "document": extraction["document"],
                        "maturity_date": str(maturity),
                        "status": "active",
                        "detail": f"Matures {maturity}.",
                    }
                )
    if any(
        f["status"] == "expired_check_for_conversion"
        for f in maturity_findings
    ):
        diligence_questions.append(
            "One or more executed CLAs are past maturity with no conversion "
            "or repayment documented — clarify their current status before "
            "relying on the outstanding-principal total."
        )

    # --- E-signature corroboration ---------------------------------------
    esignature = []
    for extraction in executed + term_sheets:
        document = extraction["document"]
        markers = esign_markers.get(document) or {}
        claimed = _value(extraction.get("signatures_complete"))
        corroborated = bool(markers) and claimed is True
        esignature.append(
            {
                "document": document,
                "signatures_complete_claimed": claimed,
                "esign_markers": markers,
                "corroborated": corroborated,
            }
        )
        if claimed is True and not markers:
            diligence_questions.append(
                f"{document!r}: execution claimed but no e-signature "
                "markers found in the raw PDF — verify wet-ink signatures "
                "or request the signature certificates."
            )

    # --- Per-lender table -------------------------------------------------
    per_lender: dict[str, dict[str, Any]] = {}
    for extraction in executed:
        for name, amount in _loan_amounts(extraction):
            key = normalize_lender_name(name)
            row = per_lender.setdefault(
                key, {"name": name, "loans": 0, "total_principal": 0.0}
            )
            row["loans"] += 1
            if amount is not None:
                row["total_principal"] += amount

    return {
        "executed_count": len(executed),
        "term_sheet_count": len(term_sheets),
        "settled_count": len(settled),
        "superseded_term_sheets": superseded_term_sheets,
        "open_term_sheets": open_term_sheets,
        "identical_terms_groups": [
            {
                "documents": group["documents"],
                "lender_count": len(group["lenders"]),
                "total_principal": group["total_principal"],
                "unknown_amounts": group["unknown_amounts"],
            }
            for group in groups.values()
        ],
        "ten_twenty_rule": ten_twenty,
        "outstanding_principal_total": outstanding_total,
        "outstanding_unknown_amounts": unknown_amounts,
        "per_lender": sorted(
            per_lender.values(), key=lambda row: -row["total_principal"]
        ),
        "maturity": maturity_findings,
        "esignature": esignature,
        "diligence_questions": diligence_questions,
    }

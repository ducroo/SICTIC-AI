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
from typing import Any, Iterable

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


def canonical_lender_map(names: Iterable[str]) -> dict[str, str]:
    """Map every normalized lender name to one canonical key per identity.

    Names that names_match ('Anna Beispiel' vs 'Anna Barbara Beispiel') share the
    longest (most specific) form as their canonical key, regardless of the
    order in which they appear.
    """
    normalized = [normalize_lender_name(name) for name in names]
    # longest first so shorter variants attach to the specific form
    canonical: dict[str, str] = {}
    for key in sorted(set(normalized), key=len, reverse=True):
        for existing in canonical.values():
            if names_match(key, existing):
                canonical[key] = existing
                break
        else:
            canonical[key] = key
    return canonical


def terms_group_key(extraction: dict[str, Any]) -> tuple:
    """The identical-terms tuple used for 10/20 non-bank grouping.

    Dates and currency are normalized first: "31.12.2027" and "2027-12-31"
    are the same terms, and splitting one round across spelling variants
    would under-report the 10-non-bank count.
    """
    maturity = _value(extraction.get("maturity_date"))
    parsed = _parse_date(maturity)
    currency = _value(extraction.get("principal_currency"))
    return (
        _value(extraction.get("interest_mode")),
        _value(extraction.get("interest_rate_pct")),
        _value(extraction.get("discount_pct")),
        _value(extraction.get("valuation_cap")),
        _value(extraction.get("valuation_floor")),
        parsed.isoformat() if parsed else maturity,
        _value(extraction.get("qefr_min_raise")),
        currency.strip().upper() if isinstance(currency, str) else currency,
    )


def _loan_amounts(extraction: dict[str, Any]) -> list[tuple[str, float | None]]:
    """(lender name, amount) pairs for one agreement.

    When per-lender amounts are unstated but the agreement states a total,
    the total is used (single lender) or apportioned equally (multi-lender,
    flagged upstream via aggregate assumptions) — an agreement's stated
    principal must never silently count as zero outstanding.
    """
    lenders = extraction.get("lenders") or []
    total = _value(extraction.get("principal_total"))
    if len(lenders) == 1:
        name = lenders[0].get("name", "unknown")
        amount = lenders[0].get("principal_amount")
        return [(name, amount if amount is not None else total)]
    stated = [lender.get("principal_amount") for lender in lenders]
    if total is not None and all(amount is None for amount in stated):
        share = total / len(lenders)
        return [
            (lender.get("name", "unknown"), share) for lender in lenders
        ]
    remainder = None
    if total is not None:
        known = sum(a for a in stated if a is not None)
        missing = sum(1 for a in stated if a is None)
        if missing:
            remainder = max(0.0, total - known) / missing
    pairs = []
    for lender in lenders:
        amount = lender.get("principal_amount")
        pairs.append(
            (lender.get("name", "unknown"),
             amount if amount is not None else remainder)
        )
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
    for extraction in executed:
        lenders = extraction.get("lenders") or []
        if (
            len(lenders) > 1
            and all(l.get("principal_amount") is None for l in lenders)
            and _value(extraction.get("principal_total")) is not None
        ):
            diligence_questions.append(
                f"{extraction['document']!r}: per-lender loan amounts are "
                "unstated; the agreement total was apportioned equally "
                "across lenders for aggregation — request the per-lender "
                "breakdown."
            )

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
        matching = {
            key
            for key in sheet_lenders
            for executed_key in executed_by_lender
            if names_match(key, executed_key)
        }
        if matching:
            superseded_term_sheets.append(sheet["document"])
            sheet_amount = _value(sheet.get("principal_total"))
            for lender_key in matching:
                matching_extractions = {
                    id(e): e
                    for executed_key, extractions_for in
                    executed_by_lender.items()
                    if names_match(lender_key, executed_key)
                    for e in extractions_for
                }.values()
                counted: set[str] = set()
                executed_amount = 0.0
                for e in matching_extractions:
                    for name, amount in _loan_amounts(e):
                        norm = normalize_lender_name(name)
                        if (
                            names_match(norm, lender_key)
                            and amount is not None
                            and (id(e), norm) not in counted
                        ):
                            counted.add((id(e), norm))
                            executed_amount += amount
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
    canonical = canonical_lender_map(
        name
        for extraction in executed
        for name, _amount in _loan_amounts(extraction)
    )

    def canon(name: str) -> str:
        key = normalize_lender_name(name)
        return canonical.get(key, key)

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
            group["lenders"].add(canon(name))
            if amount is None:
                group["unknown_amounts"] += 1
            else:
                group["total_principal"] += amount

    all_lenders: set[str] = set()
    syndicate_present = False
    for extraction in executed:
        for lender in extraction.get("lenders") or []:
            all_lenders.add(canon(lender.get("name", "")))
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
                            "in the data room. Request conversion notices "
                            "(incl. any lender-majority conversion demand "
                            "made within the contractual post-maturity "
                            "window), extension agreements, or repayment "
                            "records — or confirmation that the balance "
                            "remains outstanding as a (typically "
                            "subordinated) debt."
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
    # ``esign_markers`` carries a key ONLY for documents whose raw PDF was
    # actually scanned; absence of the key means the source is not a PDF
    # (or unavailable), which is NOT evidence against execution — the
    # extraction's quoted signature block stands on its own there.
    esignature = []
    for extraction in executed + term_sheets:
        document = extraction["document"]
        claimed = _value(extraction.get("signatures_complete"))
        if document not in esign_markers:
            esignature.append(
                {
                    "document": document,
                    "signatures_complete_claimed": claimed,
                    "esign_markers": None,
                    "corroborated": "not_applicable",
                    "note": "source is not a scannable PDF; execution "
                    "evidence rests on the extracted signature block",
                }
            )
            continue
        markers = esign_markers[document] or {}
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
            key = canon(name)
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

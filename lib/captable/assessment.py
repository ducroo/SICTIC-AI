"""Stage 3: deterministic qualitative assessment of one extracted CLA.

Pure Python over the stage-2 extraction: the LLM already extracted every
value with a verified quote; judging those values against market-standard
bands is arithmetic and rule application, so no LLM is involved here.
Bands and thresholds live in ``config/captable/assessment_rules.json``.
"""

from __future__ import annotations

from typing import Any

SEVERITY_ORDER = ("info", "medium", "high", "severe")

STATUS_STANDARD = "present_market_standard"
STATUS_DEVIATING = "present_deviating"
STATUS_ABSENT = "absent"


def _value(extraction: dict[str, Any], field: str) -> Any:
    entry = extraction.get(field)
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def _finding(
    item: str,
    status: str,
    severity: str,
    detail: str,
) -> dict[str, str]:
    return {
        "item": item,
        "status": status,
        "severity": severity,
        "detail": detail,
    }


def assess_cla(
    extraction: dict[str, Any],
    rules: dict[str, Any],
) -> list[dict[str, str]]:
    """Assess one CLA extraction; returns one finding per checklist item."""
    findings: list[dict[str, str]] = []
    v = lambda field: _value(extraction, field)  # noqa: E731

    # --- Discount ---------------------------------------------------------
    band_low, band_high = rules["discount_commercial_band_pct"]
    tax_threshold = float(rules["discount_tax_reclassification_pct"])
    discount = v("discount_pct")
    if discount is None:
        findings.append(
            _finding(
                "discount",
                STATUS_ABSENT,
                "medium",
                "No conversion discount stated.",
            )
        )
    elif discount > tax_threshold:
        findings.append(
            _finding(
                "discount",
                STATUS_DEVIATING,
                "high",
                f"Discount {discount:g}% exceeds the {tax_threshold:g}% "
                "reclassification threshold (reported ESTV practice: "
                "non-classic loan, income tax on the discount; verify "
                "with tax counsel).",
            )
        )
    elif not (band_low <= discount <= band_high):
        findings.append(
            _finding(
                "discount",
                STATUS_DEVIATING,
                "medium",
                f"Discount {discount:g}% is outside the customary "
                f"{band_low:g}-{band_high:g}% band.",
            )
        )
    else:
        findings.append(
            _finding(
                "discount",
                STATUS_STANDARD,
                "info",
                f"Discount {discount:g}% within the customary band.",
            )
        )

    # --- Valuation cap ----------------------------------------------------
    cap = v("valuation_cap")
    maturity = v("maturity_date")
    if cap is None:
        severity = "high" if maturity is None else "medium"
        detail = (
            "No valuation cap: an active investor who raises the round "
            "valuation converts at a worse price (incentive misalignment)."
        )
        if maturity is None:
            detail += " Combined with no maturity date this is aggravated."
        findings.append(
            _finding("valuation_cap", STATUS_ABSENT, severity, detail)
        )
    else:
        findings.append(
            _finding(
                "valuation_cap",
                STATUS_STANDARD,
                "info",
                f"Valuation cap of {cap:,.0f} stated.",
            )
        )

    # --- Maturity ---------------------------------------------------------
    if maturity is None:
        findings.append(
            _finding(
                "maturity_date",
                STATUS_ABSENT,
                "high",
                "No maturity date: the loan can float indefinitely, "
                "which is investor-unfriendly.",
            )
        )
    else:
        findings.append(
            _finding(
                "maturity_date",
                STATUS_STANDARD,
                "info",
                f"Maturity date {maturity} stated.",
            )
        )

    # --- Interest above safe-harbor note rate -----------------------------
    note_rate = rules.get("interest_safe_harbor_note_rate_pct")
    rate = v("interest_rate_pct")
    if (
        note_rate is not None
        and rate is not None
        and rate > float(note_rate)
        and v("interest_mode") != "safe_harbor_capped"
    ):
        findings.append(
            _finding(
                "interest_rate",
                STATUS_DEVIATING,
                "medium",
                f"Interest {rate:g}% exceeds the {float(note_rate):g}% "
                "safe-harbor reference without a safe-harbor cap — "
                "withholding/hidden-dividend exposure if the lender is a "
                "related party; verify against the current ESTV circular.",
            )
        )

    # --- Subordination ----------------------------------------------------
    subordinated = v("subordinated")
    scope = v("subordination_scope")
    if subordinated is None and scope in (None, "unclear"):
        findings.append(
            _finding(
                "subordination",
                STATUS_ABSENT,
                "high",
                "No subordination information could be extracted — treat "
                "as unsubordinated until the clause is located.",
            )
        )
    elif subordinated is False or scope == "not_subordinated":
        findings.append(
            _finding(
                "subordination",
                STATUS_ABSENT,
                "severe",
                "Loan is not subordinated (art. 725b CO): it counts "
                "toward over-indebtedness.",
            )
        )
    elif scope == "principal_only":
        findings.append(
            _finding(
                "subordination",
                STATUS_DEVIATING,
                "severe",
                "Subordination covers the principal only; accrued "
                "interest remains senior, so the company can still be "
                "technically over-indebted.",
            )
        )
    elif scope == "loan_balance_full":
        findings.append(
            _finding(
                "subordination",
                STATUS_STANDARD,
                "info",
                "Full subordination of principal and accrued interest.",
            )
        )
    else:
        findings.append(
            _finding(
                "subordination",
                STATUS_DEVIATING,
                "medium",
                "Subordination present but its covered amount is unclear.",
            )
        )

    # --- QEFR trigger -----------------------------------------------------
    qefr_present = v("qefr_present")
    qefr_min = v("qefr_min_raise")
    if qefr_present is True and qefr_min is not None:
        findings.append(
            _finding(
                "qefr_trigger",
                STATUS_STANDARD,
                "info",
                f"Qualified-round conversion with a minimum raise of "
                f"{qefr_min:,.0f}.",
            )
        )
    elif qefr_present is True:
        findings.append(
            _finding(
                "qefr_trigger",
                STATUS_DEVIATING,
                "medium",
                "Qualified-round conversion without a minimum raise "
                "threshold: the loan could convert in an arbitrarily "
                "small round.",
            )
        )
    else:
        findings.append(
            _finding(
                "qefr_trigger",
                STATUS_ABSENT,
                "high",
                "No qualified-financing conversion trigger identified.",
            )
        )

    # --- Conversion share capital source ---------------------------------
    sources = v("conversion_capital_sources") or []
    consents = v("shareholder_consents_referenced")
    if sources or consents is True:
        findings.append(
            _finding(
                "conversion_capital",
                STATUS_STANDARD,
                "info",
                "Share creation for conversion is provided for "
                f"(sources: {', '.join(sources) or 'shareholder consents'}).",
            )
        )
    else:
        findings.append(
            _finding(
                "conversion_capital",
                STATUS_ABSENT,
                "high",
                "Neither conditional capital / capital band nor "
                "shareholder consent declarations are provided for — "
                "enforceability of the conversion is at risk (SECA "
                "recommends advance shareholder consents).",
            )
        )

    # --- Denominator basis ------------------------------------------------
    basis = v("denominator_basis")
    if basis in (None, "unstated"):
        if cap is not None or v("valuation_floor") is not None:
            findings.append(
                _finding(
                    "denominator_basis",
                    STATUS_ABSENT,
                    "medium",
                    "Cap/floor present but the share-count basis "
                    "(issued vs fully diluted) is unstated — the "
                    "conversion price is ambiguous.",
                )
            )
        else:
            findings.append(
                _finding(
                    "denominator_basis",
                    STATUS_ABSENT,
                    "info",
                    "No cap/floor, so the share-count basis is not needed.",
                )
            )
    else:
        findings.append(
            _finding(
                "denominator_basis",
                STATUS_STANDARD,
                "info",
                f"Share-count basis: {basis}.",
            )
        )

    # --- Change of control ------------------------------------------------
    coc = v("coc_present")
    multiple = v("coc_repayment_multiple")
    if coc is True:
        detail = "Change-of-control conversion provided."
        if multiple is not None:
            detail += (
                f" Lender may instead demand repayment at {multiple:g}x "
                "principal — factor into exit economics."
            )
        findings.append(
            _finding("change_of_control", STATUS_STANDARD, "info", detail)
        )
    else:
        findings.append(
            _finding(
                "change_of_control",
                STATUS_ABSENT,
                "medium",
                "No change-of-control trigger: an exit before conversion "
                "leaves the lender as a mere creditor.",
            )
        )

    # --- MFN / pro-rata / SHA accession (informational) -------------------
    findings.append(
        _finding(
            "mfn_clause",
            STATUS_STANDARD if v("mfn_clause") is True else STATUS_ABSENT,
            "info",
            "Most-favored-nation clause present."
            if v("mfn_clause") is True
            else "No most-favored-nation clause; later lenders may get "
            "better terms.",
        )
    )
    findings.append(
        _finding(
            "pro_rata_rights",
            STATUS_STANDARD
            if v("pro_rata_rights") is True
            else STATUS_ABSENT,
            "info",
            "Pro-rata participation right in the next round present."
            if v("pro_rata_rights") is True
            else "No pro-rata participation right beyond conversion.",
        )
    )
    findings.append(
        _finding(
            "sha_accession",
            STATUS_STANDARD
            if v("sha_accession_required") is True
            else STATUS_ABSENT,
            "info",
            "SHA accession is a condition of conversion."
            if v("sha_accession_required") is True
            else "No SHA-accession condition identified.",
        )
    )

    # --- Interest details (informational) ---------------------------------
    for field, label in (
        ("interest_day_count", "day-count convention"),
        ("interest_compounding", "compounding mode"),
    ):
        val = v(field)
        if val in (None, "unstated"):
            findings.append(
                _finding(
                    field,
                    STATUS_ABSENT,
                    "info",
                    f"Interest {label} unstated; the accrued amount at "
                    "conversion is ambiguous.",
                )
            )

    return findings


def worst_severity(findings: list[dict[str, str]]) -> str:
    worst = "info"
    for finding in findings:
        if SEVERITY_ORDER.index(finding["severity"]) > SEVERITY_ORDER.index(
            worst
        ):
            worst = finding["severity"]
    return worst

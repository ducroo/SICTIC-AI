"""Lender-angle assessment of one CLA extraction (cla_review, design step 3).

Pure Python over a ``captable_build`` CLA extraction, the mirror image of
``lib.captable.assessment.assess_cla``: that module judges from the company's
market-standard angle, this one from the lender's. Rules and thresholds live
in ``config/cla_review/settings.json``. A rule that is not active yields an
open question with the observed value, never a judgment; a rule whose input
is not available yields ``not_evaluated`` naming the missing input.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable

from lib.captable.data import extraction_value

STATUS_FLAGGED = "flagged"
STATUS_ACCEPTABLE = "acceptable"
STATUS_ABSENT = "absent"
STATUS_OPEN_QUESTION = "open_question"
STATUS_NOT_EVALUATED = "not_evaluated"

_HIGH_WHEN_FLAGGED = {
    "valuation_cap_required",
    "maturity_conversion_required",
    "coc_repayment_multiple_minimum",
}

Verdict = tuple[str, str]  # (status, observation)


def _months_between(start: date, end: date) -> float:
    return (end.year - start.year) * 12 + (end.month - start.month) + (end.day - start.day) / 30


def _months_to_maturity(extraction: dict[str, Any], as_of: date) -> float | None:
    maturity = extraction_value(extraction, "maturity_date")
    if not isinstance(maturity, str):
        return None
    try:
        return _months_between(as_of, date.fromisoformat(maturity[:10]))
    except ValueError:
        return None


def _term(extraction: dict[str, Any], ctx: dict[str, Any]) -> tuple[float | None, Verdict | None]:
    """Months from the run date to maturity, or the verdict that stops a term-based rule."""
    months = _months_to_maturity(extraction, ctx["as_of"])
    if months is None:
        return None, (STATUS_NOT_EVALUATED, "The maturity date is missing or not a date, so the term cannot be measured.")
    if months < 0:
        return months, (STATUS_FLAGGED, f"Maturity {extraction_value(extraction, 'maturity_date')} lies before the run date "
                                        f"{ctx['as_of']}: the loan would already be due.")
    return months, None


_FRACTIONS = (
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent|per cent)", re.I), lambda m: float(m.group(1).replace(",", ".")) / 100),
    (re.compile(r"\b(\d+)\s*/\s*(\d+)\b"), lambda m: int(m.group(1)) / int(m.group(2))),
    (re.compile(r"\btwo[\s-]thirds?\b", re.I), lambda m: 2 / 3),
    (re.compile(r"\bthree[\s-]quarters?\b", re.I), lambda m: 0.75),
    (re.compile(r"\b(?:simple\s+)?majority\b|\bmore than (?:half|50)", re.I), lambda m: 0.5),
)


def _share_of_principal(text: str) -> float | None:
    """The fraction a majority clause names, when it names one."""
    for pattern, value in _FRACTIONS:
        match = pattern.search(text)
        if match:
            return value(match)
    return None


def _aggregate_loan(extraction: dict[str, Any]) -> float | None:
    for field in ("aggregate_amount_max", "aggregate_amount_min", "principal_total"):
        value = extraction_value(extraction, field)
        if isinstance(value, (int, float)):
            return float(value)
    return None


# --- one evaluator per rule ---------------------------------------------------

def _discount_minimum_pct(x, v, ctx) -> Verdict:
    discount = extraction_value(x, "discount_pct")
    if discount is None:
        return STATUS_ABSENT, "No conversion discount stated."
    if discount < v:
        return STATUS_FLAGGED, f"Discount {discount:g}% is below the proposed lender minimum of {v:g}%."
    return STATUS_ACCEPTABLE, f"Discount {discount:g}% meets the proposed lender minimum of {v:g}%."


def _discount_schedule_expected_above_months(x, v, ctx) -> Verdict:
    months, stop = _term(x, ctx)
    if stop is not None:
        return stop
    schedule = extraction_value(x, "discount_schedule")
    if months > v and schedule is None:
        return STATUS_FLAGGED, f"Term of {months:.0f} months exceeds {v:g} months and no discount schedule is stated."
    if schedule:
        return STATUS_ACCEPTABLE, f"Term of {months:.0f} months with a discount schedule: {schedule}"
    return STATUS_ACCEPTABLE, f"Term of {months:.0f} months; a schedule is only expected above {v:g} months."


def _valuation_cap_required(x, v, ctx) -> Verdict:
    cap = extraction_value(x, "valuation_cap")
    if cap is None:
        return STATUS_FLAGGED, "No valuation cap: the conversion price is unbounded."
    return STATUS_ACCEPTABLE, f"Valuation cap of {cap:,.0f} stated."


def _denominator_fully_diluted_expected(x, v, ctx) -> Verdict:
    basis = extraction_value(x, "denominator_basis")
    if basis in (None, "unstated"):
        # The design flags an unstated basis: the share count behind the cap price is undefined.
        return STATUS_FLAGGED, "Denominator basis unstated; the share count behind the cap price is undefined."
    if basis == "fully_diluted":
        return STATUS_ACCEPTABLE, "Fully diluted denominator, the investor-friendly basis."
    return STATUS_FLAGGED, f"Denominator basis '{basis}' is less investor-friendly than fully diluted."


def _qefr_threshold_minimum_multiple_of_aggregate_loan(x, v, ctx) -> Verdict:
    threshold = extraction_value(x, "qefr_min_raise")
    if threshold is None:
        return STATUS_ABSENT, "No qualified-financing threshold stated."
    aggregate = _aggregate_loan(x)
    if aggregate is None:
        return STATUS_NOT_EVALUATED, "The aggregate loan amount is unknown, so the threshold cannot be related to it."
    if threshold < v * aggregate:
        return STATUS_FLAGGED, f"Qualified-financing threshold {threshold:,.0f} is below {v:g}x the aggregate loan of {aggregate:,.0f}."
    return STATUS_ACCEPTABLE, f"Qualified-financing threshold {threshold:,.0f} is at least {v:g}x the aggregate loan of {aggregate:,.0f}."


def _qefr_threshold_maximum_multiple_of_round_target(x, v, ctx) -> Verdict:
    target = ctx.get("round_target")
    if target is None:
        return STATUS_NOT_EVALUATED, "The stated next-round target of the company is not an input yet."
    threshold = extraction_value(x, "qefr_min_raise")
    if threshold is None:
        return STATUS_ABSENT, "No qualified-financing threshold stated."
    if threshold > v * target:
        return STATUS_FLAGGED, f"Qualified-financing threshold {threshold:,.0f} exceeds {v:g}x the stated round target of {target:,.0f}."
    return STATUS_ACCEPTABLE, f"Qualified-financing threshold {threshold:,.0f} is within {v:g}x the stated round target of {target:,.0f}."


def _maturity_conversion_required(x, v, ctx) -> Verdict:
    if not extraction_value(x, "maturity_conversion_present"):
        return STATUS_FLAGGED, "No conversion mechanism at maturity: an unconverted loan is only a subordinated claim."
    price = extraction_value(x, "maturity_conversion_price")
    return STATUS_ACCEPTABLE, (
        f"Conversion at maturity stated at a price of {price:,.0f}." if isinstance(price, (int, float))
        else "Conversion at maturity stated; the price or mechanism is not a number in the document."
    )


def _term_maximum_months(x, v, ctx) -> Verdict:
    months, stop = _term(x, ctx)
    if stop is not None:
        return stop
    if months > v:
        return STATUS_FLAGGED, f"Term of {months:.0f} months exceeds the proposed maximum of {v:g} months."
    return STATUS_ACCEPTABLE, f"Term of {months:.0f} months is within the proposed maximum of {v:g} months."


def _interest_safe_harbor_rate_pct(x, v, ctx) -> Verdict:
    if v is None:
        return STATUS_NOT_EVALUATED, "The current ESTV safe-harbor rate is not configured."
    if extraction_value(x, "interest_mode") == "safe_harbor_capped":
        return STATUS_ACCEPTABLE, "Interest is capped at the safe-harbor rate."
    rate = extraction_value(x, "interest_rate_pct")
    if rate is None:
        return STATUS_ABSENT, "Interest rate unstated."
    if rate > v:
        return STATUS_FLAGGED, f"Interest {rate:g}% exceeds the safe-harbor rate of {v:g}%; relevant when insiders lend."
    return STATUS_ACCEPTABLE, f"Interest {rate:g}% is within the safe-harbor rate of {v:g}%."


def _coc_repayment_multiple_minimum(x, v, ctx) -> Verdict:
    if not extraction_value(x, "coc_present"):
        return STATUS_FLAGGED, "No change-of-control clause: neither conversion nor repayment is secured on a sale."
    multiple = extraction_value(x, "coc_repayment_multiple")
    if multiple is None:
        return STATUS_ABSENT, "Change-of-control clause present without a repayment multiple; check that it at least converts at the cap."
    if multiple < v:
        return STATUS_FLAGGED, f"Change-of-control repayment multiple {multiple:g}x is below the proposed minimum of {v:g}x."
    return STATUS_ACCEPTABLE, f"Change-of-control repayment multiple {multiple:g}x meets the proposed minimum of {v:g}x."


def _lender_majority_minimum_share_of_principal(x, v, ctx) -> Verdict:
    majority = extraction_value(x, "investor_majority")
    if not majority:
        return STATUS_FLAGGED, "The lender majority for waivers, amendments and extensions is undefined."
    share = _share_of_principal(str(majority))
    if share is None:
        return STATUS_NOT_EVALUATED, f"Lender majority defined as '{majority}' but no share of principal can be read from it; compare by hand with the proposed minimum of {v:.0%}."
    if share < v - 0.005:  # configured fractions are rounded (two thirds is stored as 0.6667)
        return STATUS_FLAGGED, f"Lender majority '{majority}' ({share:.0%}) is below the proposed minimum of {v:.0%} of principal."
    return STATUS_ACCEPTABLE, f"Lender majority '{majority}' ({share:.0%}) meets the proposed minimum of {v:.0%} of principal."


def _exclusivity_flagged(x, v, ctx) -> Verdict:
    if extraction_value(x, "exclusivity_present"):
        until = extraction_value(x, "exclusivity_until")
        return STATUS_FLAGGED, f"Exclusivity present{f' until {until}' if until else ''}; not recommended for angel rounds."
    return STATUS_ACCEPTABLE, "No exclusivity undertaking."


def _legal_fees_each_party_own(x, v, ctx) -> Verdict:
    own = extraction_value(x, "legal_fees_each_party_own")
    if own is None:
        return STATUS_ABSENT, "Cost allocation unstated."
    if own is False:
        return STATUS_FLAGGED, "Costs are not borne by each party on its own."
    return STATUS_ACCEPTABLE, "Each party bears its own costs."


_ECONOMIC_WORDS = ("interest", "discount", "cap", "valuation", "conversion", "amount", "exclusiv")


def _binding_provisions_limited(x, v, ctx) -> Verdict:
    binding = extraction_value(x, "binding_provisions")
    if not binding:
        return STATUS_ABSENT, "The term sheet does not distinguish binding from non-binding provisions."
    lowered = str(binding).lower()
    if any(word in lowered for word in _ECONOMIC_WORDS):
        return STATUS_FLAGGED, f"Binding provisions go beyond confidentiality, costs, effect and law: {binding}"
    return STATUS_ACCEPTABLE, f"Binding provisions limited to: {binding}"


def _documentation_seca_form_expected(x, v, ctx) -> Verdict:
    form = extraction_value(x, "documentation_form")
    if form in ("seca_short_form", "seca_long_form"):
        return STATUS_ACCEPTABLE, f"Definitive agreements follow the SECA model ({form})."
    if form == "bespoke":
        return STATUS_FLAGGED, "Definitive agreements follow bespoke documentation, not the SECA model."
    return STATUS_ABSENT, "The documentation form is unstated."


def _non_bank_rules(x, v, ctx) -> Verdict:
    """The 10/20 counts after N members join, from question 2 (``loan_context``), against the configured limits."""
    counts = ctx.get("non_bank_counts")
    if counts is None:
        return STATUS_NOT_EVALUATED, "Needs the existing loans of the company (question 2 on a reusable cap-table snapshot)."
    identical, total = counts["max_lenders_on_identical_terms"], counts["total_lenders_all_terms"]
    limits = f"{identical} on identical terms (limit {v['identical_terms_lenders']}), {total} in total (limit {v['total_lenders']})"
    if identical > v["identical_terms_lenders"] or total > v["total_lenders"]:
        return STATUS_FLAGGED, f"After the syndicate joins the company would have {limits}: interest becomes subject to withholding tax."
    return STATUS_ACCEPTABLE, f"After the syndicate joins the company would have {limits}."


EVALUATORS: dict[str, Callable[[dict[str, Any], Any, dict[str, Any]], Verdict]] = {
    "discount_minimum_pct": _discount_minimum_pct,
    "discount_schedule_expected_above_months": _discount_schedule_expected_above_months,
    "valuation_cap_required": _valuation_cap_required,
    "denominator_fully_diluted_expected": _denominator_fully_diluted_expected,
    "qefr_threshold_minimum_multiple_of_aggregate_loan": _qefr_threshold_minimum_multiple_of_aggregate_loan,
    "qefr_threshold_maximum_multiple_of_round_target": _qefr_threshold_maximum_multiple_of_round_target,
    "maturity_conversion_required": _maturity_conversion_required,
    "term_maximum_months": _term_maximum_months,
    "interest_safe_harbor_rate_pct": _interest_safe_harbor_rate_pct,
    "coc_repayment_multiple_minimum": _coc_repayment_multiple_minimum,
    "lender_majority_minimum_share_of_principal": _lender_majority_minimum_share_of_principal,
    "exclusivity_flagged": _exclusivity_flagged,
    "legal_fees_each_party_own": _legal_fees_each_party_own,
    "binding_provisions_limited": _binding_provisions_limited,
    "documentation_seca_form_expected": _documentation_seca_form_expected,
    "non_bank_rules": _non_bank_rules,
}


def _severity(status: str, rule: str) -> str:
    if status == STATUS_FLAGGED:
        return "high" if rule in _HIGH_WHEN_FLAGGED else "medium"
    if status == STATUS_ABSENT:
        return "medium"
    return "info"


def assess_lender_angle(
    extraction: dict[str, Any],
    settings: dict[str, Any],
    *,
    as_of: date | None = None,
    round_target: float | None = None,
    non_bank_counts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One finding per configured rule, in configuration order.

    ``settings`` is the validated ``config/cla_review/settings.json`` content.
    Active rules judge (``flagged`` / ``acceptable`` / ``absent``); inactive
    rules only raise an ``open_question`` carrying the observation and the
    rule's review status. Rules whose input is unavailable are
    ``not_evaluated`` whatever their activation. ``non_bank_counts`` is the
    "after" state of ``loan_context``'s 10/20 block when question 2 ran on a
    reusable snapshot.
    """
    context = {"as_of": as_of or date.today(), "round_target": round_target, "non_bank_counts": non_bank_counts}
    inputs = set(settings.get("inputs_not_rules", ()))
    findings: list[dict[str, Any]] = []
    for name, rule in settings["rules"].items():
        if name in inputs:
            continue
        evaluator = EVALUATORS.get(name)
        if evaluator is None:
            raise ValueError(f"cla_review rule {name!r} has no evaluator in lib/cla_review/assessment.py.")
        verdict, observation = evaluator(extraction, rule["value"], context)
        if verdict == STATUS_NOT_EVALUATED or rule["active"]:
            status, detail = verdict, observation
        else:
            status = STATUS_OPEN_QUESTION
            detail = (
                f"Not judged: rule {name} has status {rule['status']} and is inactive. "
                f"Observed: {observation}"
            )
        findings.append({
            "item": name,
            "status": status,
            "severity": _severity(status, name),
            "detail": detail,
            "rule": name,
            "rule_status": rule["status"],
            "active": bool(rule["active"]),
        })
    return findings

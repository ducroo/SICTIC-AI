"""Stage 2: extract the terms of one convertible loan agreement."""

from __future__ import annotations

from typing import Any

from lib.captable.documents import normalize_for_matching
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Field values that assert absence/uncertainty and therefore need no quote.
_NO_QUOTE_VALUES = frozenset({"unstated", "unclear", "not_subordinated"})

# Booleans whose False asserts "no such clause exists" (an absence claim that
# no quote can prove) rather than a documented property of an existing clause.
# These always need a missing_terms entry when False, quoted or not.
_PRESENCE_BOOLEAN_FIELDS = frozenset(
    {
        "qefr_present",
        "coc_present",
        "maturity_conversion_present",
        "mfn_clause",
        "pro_rata_rights",
    }
)

# Top-level {value, quote} fields of the extraction schema.
_QUOTED_FIELDS = (
    "borrower_name",
    "execution_date",
    "signatures_complete",
    "principal_total",
    "principal_currency",
    "interest_mode",
    "interest_rate_pct",
    "interest_safe_harbor_rate_pct",
    "interest_day_count",
    "interest_compounding",
    "maturity_date",
    "qefr_present",
    "qefr_min_raise",
    "qefr_min_new_money",
    "qefr_mandatory",
    "coc_present",
    "coc_mandatory",
    "coc_repayment_multiple",
    "maturity_conversion_present",
    "maturity_conversion_mandatory",
    "maturity_conversion_price",
    "valuation_cap",
    "discount_pct",
    "discount_schedule",
    "valuation_floor",
    "denominator_basis",
    "subordinated",
    "subordination_scope",
    "mfn_clause",
    "pro_rata_rights",
    "conversion_capital_sources",
    "shareholder_consents_referenced",
    "sha_accession_required",
    "governing_law",
)


def _quote_found(quote: str, normalized_text: str) -> bool:
    """A quote matches when every ellipsis-separated fragment is found.

    Models abbreviate long clauses with "..."/"…"; requiring each fragment
    verbatim keeps the evidence property while tolerating the abbreviation.
    """
    import re

    fragments = [
        fragment
        for fragment in re.split(r"\.{3,}|…", quote)
        if fragment.strip()
    ]
    if not fragments:
        return False
    return all(
        normalize_for_matching(fragment) in normalized_text
        for fragment in fragments
    )


def _needs_quote(value: Any) -> bool:
    """True when a value is a positive claim that requires evidence."""
    if value is None or value is False:
        return False
    if isinstance(value, str) and value in _NO_QUOTE_VALUES:
        return False
    if isinstance(value, list) and not value:
        return False  # empty conversion_capital_sources = absence claim
    return True


def _is_absence_claim(field: str, value: Any, quote: Any) -> bool:
    """True when the field asserts absence and must appear in missing_terms."""
    if value is None:
        return True
    if isinstance(value, str) and value == "unstated":
        return True
    if value is False and field in _PRESENCE_BOOLEAN_FIELDS:
        return True
    if value is False and quote is None:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def review_cla_extraction(document_text: str):
    """Build a reviewer enforcing the evidence rules against ``document_text``."""
    normalized_text = normalize_for_matching(document_text)

    def reviewer(output: Any) -> Review[Any]:
        if not isinstance(output, dict):
            return Review(output, ("Response must be a JSON object.",))
        problems: list[str] = []
        absence_fields: list[str] = []

        for field in _QUOTED_FIELDS:
            entry = output.get(field)
            if not isinstance(entry, dict):
                continue  # schema validation reports shape errors
            value, quote = entry.get("value"), entry.get("quote")
            if _needs_quote(value) and not quote:
                problems.append(
                    f"{field}: value {value!r} requires a verbatim quote."
                )
            if quote and not _quote_found(quote, normalized_text):
                problems.append(
                    f"{field}: quote not found verbatim in the document "
                    f"text: {quote!r}. Copy the snippet exactly as it "
                    "appears (whitespace differences are tolerated)."
                )
            if _is_absence_claim(field, value, quote):
                absence_fields.append(field)

        for lender in output.get("lenders", []):
            if not isinstance(lender, dict):
                continue
            quote = lender.get("quote")
            if quote and not _quote_found(quote, normalized_text):
                problems.append(
                    f"lenders[{lender.get('name')!r}]: quote not found "
                    f"verbatim in the document text: {quote!r}."
                )

        covered = {
            entry.get("term")
            for entry in output.get("missing_terms", [])
            if isinstance(entry, dict)
        }
        uncovered = [
            field for field in absence_fields if field not in covered
        ]
        if uncovered:
            problems.append(
                "Every absent/unstated term (and every false boolean "
                "without a quote) needs a missing_terms entry named after "
                f"the schema field, with sections_scanned. Uncovered: "
                f"{uncovered}."
            )
        return Review(output, tuple(problems))

    return reviewer


async def extract_cla(
    dataset_name: str,
    filename: str,
    document_text: str,
) -> dict[str, Any]:
    """Extract the term schema from one CLA/term-sheet document."""
    config = load_repository_config("captable")
    prompt = (
        f"{config['cla_extraction_prompt'].strip()}\n\n"
        f"### DOCUMENT: {filename}\n\n{document_text}"
    )
    result = await generate_json(
        prompt,
        config["cla_extraction_response_schema"],
        reviewer=review_cla_extraction(document_text),
    )
    if not isinstance(result, dict):
        raise ValueError("CLA extraction response must be a JSON object.")
    result["document"] = filename
    result["dataset"] = dataset_name
    return result

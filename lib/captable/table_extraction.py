"""Stage 5: extract cap table, share register, and pool documents."""

from __future__ import annotations

from typing import Any
import math
import re

from lib.captable.aggregation import normalize_lender_name
from lib.captable.documents import normalize_for_matching
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Extracted holdings may deviate from the table's own totals by at most this
# share (covers rounding rows); larger gaps mean silently dropped rows.
COMPLETENESS_TOLERANCE = 0.005


def _numbers_in_quote(quote: str) -> set[float]:
    """Recognize plain and commonly grouped/decimal source numerals."""
    # Thousands separators: apostrophe, typographic apostrophe, narrow or
    # plain spaces, and PDF conversions that pad the apostrophe with spaces
    # ("145 ' 832"). Only join when exactly three digits follow.
    quote = re.sub(r"(?<=\d)[ \u00a0\u202f]*['\u2019][ \u00a0\u202f]*(?=\d{3}(?:\D|$))", "", quote)
    quote = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", quote)
    values = set()
    for token in re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*", quote):
        variants = [token.replace(",", ""), token.replace(".", "").replace(",", ".")]
        for variant in variants:
            try:
                values.add(float(variant))
            except ValueError:
                pass
    return values


_IMPLICIT_ZERO = re.compile(r"(?<![\w.])(?:-|\u2013|\u2014|n/?a|none|nil|keine|0)(?![\w.])|\|\s*\|", re.IGNORECASE)
_MAX_SUBSET_SUMS = 20000


def _has_implicit_zero_marker(quote: str) -> bool:
    """A dash, 'none', an empty table cell or a literal 0 stands for zero."""
    return bool(_IMPLICIT_ZERO.search(quote))


def _subset_sums(numbers: set[float]) -> set[float]:
    """Sums of two or more quoted numbers, for values reported as totals.

    Bounded so a quote full of percentages and dates cannot explode the set.
    """
    positive = sorted(n for n in numbers if n > 0)
    reachable: set[int] = {0}
    for number in positive:
        cents = round(number * 100)
        reachable |= {total + cents for total in reachable}
        if len(reachable) > _MAX_SUBSET_SUMS:
            break
    singles = {round(n * 100) for n in positive}
    return {total / 100 for total in reachable if total and total not in singles}


def _identity_in_source(identity: str, normalized_document: str, document_tokens: set[str]) -> bool:
    """The name appears contiguously, or every token of a multi-token name does."""
    if normalize_for_matching(identity) in normalized_document:
        return True
    tokens = normalize_lender_name(identity).split()
    return len(tokens) >= 2 and all(token in document_tokens for token in tokens)


def _review_evidence(output: dict, document_text: str) -> list[str]:
    normalized = normalize_for_matching(document_text)
    document_tokens = set(normalize_lender_name(document_text).split())
    problems = []

    def check(label, row, *, identity=None):
        quote = row.get("quote") or ""
        # A quote is a list of source fragments, not one contiguous block:
        # the prompt asks for the column header next to a row, a summed
        # value needs every summed line, and converted PDFs put page
        # markers and merged cells between lines. Each fragment (split on
        # line breaks and ellipses) must appear verbatim on its own.
        fragments = [
            normalize_for_matching(fragment)
            for fragment in re.split(r"\r?\n|\.\.\.|\u2026", quote)
        ]
        fragments = [fragment for fragment in fragments if fragment]
        if not fragments or any(fragment not in normalized for fragment in fragments):
            problems.append(f"{label}: quote missing or not found verbatim in source.")
            return
        # Names often sit in a merged cell above the quoted certificate or
        # holding line, and converted PDFs interleave name tokens with
        # certificate numbers; the source as a whole must still contain
        # the name, contiguously or token by token.
        if identity and not _identity_in_source(str(identity), normalized, document_tokens):
            problems.append(f"{label}: identity {identity!r} is not found in the source.")
        quoted_numbers = _numbers_in_quote(quote)
        quoted_sums = _subset_sums(quoted_numbers)
        zero_marker = _has_implicit_zero_marker(quote)
        digit_stream = re.sub(r"\D", "", quote)

        def evidenced(value: float) -> bool:
            if any(math.isclose(value, number, rel_tol=1e-9, abs_tol=1e-9) for number in quoted_numbers):
                return True
            # PDF conversion sometimes breaks a numeral with a stray space
            # ("21'66 6"); a whole number of four or more digits is accepted
            # when its digits appear consecutively in the quote.
            if float(value).is_integer() and value >= 1000 and str(int(value)) in digit_stream:
                return True
            # A dash, "none" or an empty cell in the source is how a zero is
            # written; the row may report it as 0.
            if value == 0 and zero_marker:
                return True
            # A holding split over several source lines is reported as their
            # sum; accept it when the summed lines are all quoted.
            return any(math.isclose(value, total, rel_tol=1e-9, abs_tol=0.005) for total in quoted_sums)

        def check_numbers(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not evidenced(value):
                    problems.append(f"{label}: numeric value {value} is not evidenced by its quote.")
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key != "quote":
                        check_numbers(child)
            elif isinstance(value, list):
                for child in value:
                    check_numbers(child)
        check_numbers(row)

    for collection in ("stakeholders", "share_classes", "entries", "pools"):
        for index, row in enumerate(output.get(collection, [])):
            check(f"{collection}[{index}]", row, identity=row.get("name") or row.get("label"))
    for field in ("as_of_date", "fully_diluted_definition"):
        entry = output.get(field) or {}
        if entry.get("value") not in (None, "unstated"):
            check(field, entry)
    if output.get("totals"):
        check("totals", output["totals"])
    return problems


def _review_table_evidence(document_text: str):
    def reviewer(output):
        if not isinstance(output, dict):
            return Review(output, ("Response must be a JSON object.",))
        return Review(output, tuple(_review_evidence(output, document_text)))
    return reviewer


def _review_captable(document_text: str):
    normalized_text = normalize_for_matching(document_text)

    def reviewer(output: Any) -> Review[Any]:
        if not isinstance(output, dict):
            return Review(output, ("Response must be a JSON object.",))
        problems: list[str] = _review_evidence(output, document_text)

        # A fully-diluted definition must be evidenced by definitional
        # wording, not by a table/totals row (the model's favorite dodge).
        fd = output.get("fully_diluted_definition") or {}
        if fd.get("value") not in (None, "unstated"):
            fd_quote = fd.get("quote") or ""
            if not fd_quote or "|" in fd_quote:
                problems.append(
                    "fully_diluted_definition: a table row is not evidence "
                    "of which dilution concept the numbers use; quote the "
                    "definitional wording or set the value to 'unstated'."
                )

        # Row-completeness guard: the sum of extracted holdings must match
        # the table's own per-class totals, otherwise rows were dropped.
        sums: dict[str, float] = {}
        for stakeholder in output.get("stakeholders", []):
            for holding in stakeholder.get("holdings", []):
                class_id = holding.get("class_id")
                count = holding.get("count")
                if isinstance(count, (int, float)) and class_id:
                    sums[class_id] = sums.get(class_id, 0.0) + count
        for total in (output.get("totals") or {}).get("by_class", []):
            class_id = total.get("class_id")
            stated = total.get("issued_total")
            if not class_id or not isinstance(stated, (int, float)) or not stated:
                continue
            extracted = sums.get(class_id, 0.0)
            if abs(extracted - stated) / stated > COMPLETENESS_TOLERANCE:
                problems.append(
                    f"Extracted {class_id} holdings sum to {extracted:,.0f} "
                    f"but the table's total is {stated:,.0f} — holder rows "
                    "are missing or double-counted (group rows must not be "
                    "extracted as holders). Re-extract every holder row."
                )
        return Review(output, tuple(problems))

    return reviewer


async def extract_captable(
    dataset_name: str, filename: str, document_text: str
) -> dict[str, Any]:
    """Extract one current-cap-table document."""
    config = load_repository_config("captable_build")
    prompt = (
        f"{config['captable_extraction_prompt'].strip()}\n\n"
        f"### DOCUMENT: {filename}\n\n{document_text}"
    )
    result = await generate_json(
        prompt,
        config["captable_extraction_response_schema"],
        reviewer=_review_captable(document_text),
    )
    if not isinstance(result, dict):
        raise ValueError("Cap-table extraction must be a JSON object.")
    result["document"] = filename
    result["dataset"] = dataset_name
    return result


async def extract_register(
    dataset_name: str, filename: str, document_text: str
) -> dict[str, Any]:
    """Extract current holdings from one share-register document."""
    config = load_repository_config("captable_build")
    prompt = (
        f"{config['register_extraction_prompt'].strip()}\n\n"
        f"### DOCUMENT: {filename}\n\n{document_text}"
    )
    result = await generate_json(
        prompt, config["register_extraction_response_schema"],
        reviewer=_review_table_evidence(document_text),
    )
    if not isinstance(result, dict):
        raise ValueError("Register extraction must be a JSON object.")
    result["document"] = filename
    result["dataset"] = dataset_name
    return result


async def extract_pools(
    dataset_name: str, filename: str, document_text: str
) -> dict[str, Any]:
    """Extract pool figures from one ESOP/PSOP overview document."""
    config = load_repository_config("captable_build")
    prompt = (
        f"{config['pool_extraction_prompt'].strip()}\n\n"
        f"### DOCUMENT: {filename}\n\n{document_text}"
    )
    result = await generate_json(
        prompt, config["pool_extraction_response_schema"],
        reviewer=_review_table_evidence(document_text),
    )
    if not isinstance(result, dict):
        raise ValueError("Pool extraction must be a JSON object.")
    result["document"] = filename
    result["dataset"] = dataset_name
    return result

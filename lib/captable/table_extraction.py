"""Stage 5: extract cap table, share register, and pool documents."""

from __future__ import annotations

from typing import Any
from lib.captable.documents import normalize_for_matching
from lib.captable.table_evidence import field_evidenced, numbers, quoted_rows, source_rows
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Extracted holdings may deviate from the table's own totals by at most this
# share (covers rounding rows); larger gaps mean silently dropped rows.
COMPLETENESS_TOLERANCE = 0.005


def _numbers_in_quote(quote: str) -> set[float]:
    """Recognize source numerals without combining cells."""
    return {float(value) for cell in quote.split("|") for value in numbers(cell)}


def _review_evidence(output: dict, document_text: str) -> list[str]:
    rows = source_rows(document_text)
    problems = []

    def check(label, row, *, identity=None, share_class=None):
        try:
            evidence = quoted_rows(row.get("quote") or "", rows, identity, share_class)
        except ValueError as error:
            problems.append(f"{label}: {error}.")
            return

        def check_numbers(value, field="", class_id=None):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not field_evidenced(value, field, class_id, evidence, identity, row.get("kind")):
                    problems.append(
                        f"{label}.{field}: numeric value {value} is not evidenced by "
                        "its holder's quoted column. Quote complete rows and headers; "
                        "use null and an assumption for ambiguous or unstated values."
                    )
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key != "quote":
                        check_numbers(child, key, value.get("class_id", class_id))
            elif isinstance(value, list):
                for child in value:
                    check_numbers(child, field, class_id)
        check_numbers(row)

    for collection in ("stakeholders", "share_classes", "entries", "pools"):
        for index, row in enumerate(output.get(collection, [])):
            check(f"{collection}[{index}]", row, identity=row.get("name") or row.get("label"),
                  share_class=row.get("id") if collection == "share_classes" else None)
    for field in ("as_of_date", "fully_diluted_definition"):
        entry = output.get(field) or {}
        if entry.get("value") not in (None, "unstated"):
            check(field, entry)
    if output.get("totals"):
        check("totals", output["totals"])
    return problems


def _review_table_evidence(document_text: str):
    def reviewer(output):
        return Review(output, tuple(_review_evidence(output, document_text)))
    return reviewer


def _review_captable(document_text: str):
    normalized_text = normalize_for_matching(document_text)

    def reviewer(output: Any) -> Review[Any]:
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
    result["document"] = filename
    result["dataset"] = dataset_name
    return result

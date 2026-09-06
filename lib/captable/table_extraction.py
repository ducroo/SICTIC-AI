"""Stage 5: extract cap table, share register, and pool documents."""

from __future__ import annotations

from typing import Any

from lib.captable.documents import normalize_for_matching
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Extracted holdings may deviate from the table's own totals by at most this
# share (covers rounding rows); larger gaps mean silently dropped rows.
COMPLETENESS_TOLERANCE = 0.005


def _review_captable(document_text: str):
    normalized_text = normalize_for_matching(document_text)

    def reviewer(output: Any) -> Review[Any]:
        if not isinstance(output, dict):
            return Review(output, ("Response must be a JSON object.",))
        problems: list[str] = []

        quote = (output.get("totals") or {}).get("quote")
        if quote and normalize_for_matching(quote) not in normalized_text:
            problems.append(
                f"totals.quote not found verbatim in the document: {quote!r}."
            )

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
    config = load_repository_config("captable")
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
    config = load_repository_config("captable")
    prompt = (
        f"{config['register_extraction_prompt'].strip()}\n\n"
        f"### DOCUMENT: {filename}\n\n{document_text}"
    )
    result = await generate_json(
        prompt, config["register_extraction_response_schema"]
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
    config = load_repository_config("captable")
    prompt = (
        f"{config['pool_extraction_prompt'].strip()}\n\n"
        f"### DOCUMENT: {filename}\n\n{document_text}"
    )
    result = await generate_json(
        prompt, config["pool_extraction_response_schema"]
    )
    if not isinstance(result, dict):
        raise ValueError("Pool extraction must be a JSON object.")
    result["document"] = filename
    result["dataset"] = dataset_name
    return result

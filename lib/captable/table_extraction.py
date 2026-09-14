"""Stage 5: extract cap table, share register, and pool documents."""

from __future__ import annotations

from typing import Any

from lib.captable.table_evidence import (
    DOCUMENT_HEADINGS, ROW_SCOPE, TABLE_SCOPE, QuoteError, Source, numbers, resolve_quote,
)
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Extracted holdings may deviate from the table's own totals by at most this
# share (covers rounding rows); larger gaps mean silently dropped rows.
COMPLETENESS_TOLERANCE = 0.005
POOL_FIELDS = frozenset({"total", "granted", "unallocated"})


def _numbers_in_quote(quote: str) -> set[float]:
    """Recognize source numerals cell by cell, never joining across cells."""
    return {float(value) for cell in quote.split("|") for value in numbers(cell)}


def _review_evidence(output: dict, document_text: str) -> list[str]:
    """Every extracted row must be evidenced by its quote; see table_evidence."""
    source = Source(document_text)
    problems: list[str] = []

    def check(label: str, row: dict, *, identity: str | None = None, scope: str = ROW_SCOPE) -> None:
        try:
            evidence = resolve_quote(row.get("quote") or "", source, identity, scope)
        except QuoteError as error:
            problems.append(f"{label}: {error}")
            return
        if not evidence.identity_found():
            problems.append(
                f"{label}: identity {identity!r} is not named by the quoted source rows, "
                "the named row above a run of nameless rows, a column header, a section "
                "row of the same table, or the text directly above the table. Quote the "
                "source row that names it, keeping the source wording, or drop the row."
            )
            return

        ignored = "".join(
            f" The quoted row {line.text[:120]!r} does not name {identity!r} (not in its cells, "
            "in the named row above its nameless rows, in a header, a section row or the text "
            "above the table) and was ignored."
            for line in evidence.ignored_rows()[:2]
        )

        def derived(value, field: str) -> bool:
            """The pool prompt asks to derive the third pool figure from two stated ones."""
            if field not in POOL_FIELDS or not all(isinstance(row.get(f), (int, float)) for f in POOL_FIELDS - {field}):
                return False
            total, granted, unallocated = (row.get(f) for f in ("total", "granted", "unallocated"))
            expected = {"total": granted + unallocated, "granted": total - unallocated, "unallocated": total - granted}[field]
            return abs(value - expected) < 1e-6 and all(
                evidence.evidenced(row[f], f, None) for f in POOL_FIELDS - {field}
            )

        def check_numbers(value, field: str = "", class_id: str | None = None) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                if not evidence.evidenced(value, field, class_id) and not derived(value, field):
                    problems.append(
                        f"{label}.{field}: numeric value {value} is not evidenced by the "
                        f"quoted source cells ({evidence.describe_numbers(field, class_id)})."
                        f"{ignored} Quote the complete source row(s) whose cells state this "
                        "value for this holder; when the source does not state it, report "
                        "null and an assumption. A blank cell or an absent column is null, never 0."
                    )
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key != "quote":
                        check_numbers(child, key, value.get("class_id", class_id))
            elif isinstance(value, list):
                for child in value:
                    check_numbers(child, field, class_id)

        check_numbers(row)

    # A share class is named by its table (a column, a label row); a pool
    # by its letter's heading; a holder only by rows that carry its name.
    scopes = {"share_classes": TABLE_SCOPE, "pools": DOCUMENT_HEADINGS}
    for collection in ("stakeholders", "share_classes", "entries", "pools"):
        for index, row in enumerate(output.get(collection, [])):
            check(f"{collection}[{index}]", row, identity=row.get("name") or row.get("label"),
                  scope=scopes.get(collection, ROW_SCOPE))
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

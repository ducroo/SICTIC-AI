"""Tests for the captable_build slice-1 stages (no LLM calls)."""

from __future__ import annotations

import json
from pathlib import Path

from lib.captable.classification import (
    DOCUMENT_CLASSES,
    _review_classification,
    _specialized_schema,
)
from lib.captable.cla_extraction import review_cla_extraction
from lib.captable.documents import normalize_for_matching
from lib.infrastructure.ai_text_generation.json import validate_schema

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "captable"


def _load(name: str) -> dict:
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


def test_classification_schema_is_valid() -> None:
    validate_schema(_load("classification_response_schema.json"))


def test_cla_extraction_schema_is_valid() -> None:
    validate_schema(_load("cla_extraction_response_schema.json"))


def test_document_classes_match_schema_enum() -> None:
    schema = _load("classification_response_schema.json")
    enum = schema["properties"]["documents"]["items"]["properties"][
        "document_class"
    ]["enum"]
    assert tuple(enum) == DOCUMENT_CLASSES


def test_specialized_schema_pins_filenames() -> None:
    schema = _load("classification_response_schema.json")
    filenames = ["a.pdf", "b.xlsx", "c.md"]
    specialized = _specialized_schema(schema, filenames)
    documents = specialized["properties"]["documents"]
    assert documents["minItems"] == documents["maxItems"] == 3
    assert documents["items"]["properties"]["filename"]["enum"] == filenames
    # The base schema must remain untouched.
    assert "minItems" not in schema["properties"]["documents"]


def test_classification_reviewer_requires_exact_file_set() -> None:
    reviewer = _review_classification(["a.pdf", "b.pdf"])
    good = {
        "documents": [{"filename": "a.pdf"}, {"filename": "b.pdf"}]
    }
    assert not reviewer(good).problems

    missing = {"documents": [{"filename": "a.pdf"}]}
    assert reviewer(missing).problems

    duplicated = {
        "documents": [{"filename": "a.pdf"}, {"filename": "a.pdf"}]
    }
    assert reviewer(duplicated).problems


def _minimal_extraction(**overrides) -> dict:
    """A schema-shaped extraction where everything is absent but covered."""
    quoted_null = {"value": None, "quote": None}
    fields = {
        "lenders": [
            {
                "name": "Jane Angel",
                "kind": "individual",
                "domicile": "CH",
                "principal_amount": None,
                "quote": "Jane Angel, Zurich",
            }
        ],
        "borrower_name": quoted_null,
        "status": "term_sheet",
        "status_evidence": "no signatures visible",
        "execution_date": quoted_null,
        "signatures_complete": quoted_null,
        "principal_total": quoted_null,
        "principal_currency": quoted_null,
        "interest_mode": {"value": "unstated", "quote": None},
        "interest_rate_pct": quoted_null,
        "interest_day_count": {"value": "unstated", "quote": None},
        "interest_compounding": {"value": "unstated", "quote": None},
        "maturity_date": quoted_null,
        "qefr_present": quoted_null,
        "qefr_min_raise": quoted_null,
        "qefr_mandatory": quoted_null,
        "coc_present": quoted_null,
        "coc_mandatory": quoted_null,
        "maturity_conversion_present": quoted_null,
        "maturity_conversion_mandatory": quoted_null,
        "valuation_cap": quoted_null,
        "discount_pct": quoted_null,
        "discount_schedule": quoted_null,
        "valuation_floor": quoted_null,
        "denominator_basis": {"value": "unstated", "quote": None},
        "subordinated": quoted_null,
        "subordination_scope": {"value": "unclear", "quote": None},
        "mfn_clause": quoted_null,
        "pro_rata_rights": quoted_null,
        "conversion_capital_source": {"value": "unstated", "quote": None},
        "governing_law": quoted_null,
    }
    fields.update(overrides)
    absent = [
        name
        for name, entry in fields.items()
        if isinstance(entry, dict)
        and (
            entry.get("value") is None
            or entry.get("value") == "unstated"
            or (entry.get("value") is False and entry.get("quote") is None)
        )
    ]
    fields["missing_terms"] = [
        {"term": name, "sections_scanned": ["whole document"]}
        for name in absent
    ]
    return fields


DOC_TEXT = (
    "Convertible Loan Agreement between Jane Angel, Zurich (the Lender) "
    "and Example AG. The loan shall bear interest at 5% per annum. "
    "The valuation cap shall be CHF 5,000,000."
)


def test_extraction_reviewer_accepts_covered_absences() -> None:
    reviewer = review_cla_extraction(DOC_TEXT)
    assert not reviewer(_minimal_extraction()).problems


def test_extraction_reviewer_accepts_real_quote() -> None:
    reviewer = review_cla_extraction(DOC_TEXT)
    extraction = _minimal_extraction(
        valuation_cap={
            "value": 5000000,
            "quote": "valuation cap shall be  CHF 5,000,000",
        }
    )
    assert not reviewer(extraction).problems


def test_extraction_reviewer_rejects_fabricated_quote() -> None:
    reviewer = review_cla_extraction(DOC_TEXT)
    extraction = _minimal_extraction(
        valuation_cap={
            "value": 5000000,
            "quote": "the cap amounts to five million francs",
        }
    )
    assert any(
        "not found" in problem for problem in reviewer(extraction).problems
    )


def test_extraction_reviewer_rejects_value_without_quote() -> None:
    reviewer = review_cla_extraction(DOC_TEXT)
    extraction = _minimal_extraction(
        discount_pct={"value": 20, "quote": None}
    )
    assert any(
        "requires a verbatim quote" in problem
        for problem in reviewer(extraction).problems
    )


def test_extraction_reviewer_rejects_uncovered_absence() -> None:
    reviewer = review_cla_extraction(DOC_TEXT)
    extraction = _minimal_extraction()
    extraction["missing_terms"] = [
        entry
        for entry in extraction["missing_terms"]
        if entry["term"] != "valuation_cap"
    ]
    assert any(
        "valuation_cap" in problem
        for problem in reviewer(extraction).problems
    )


def test_normalize_for_matching_collapses_ocr_whitespace() -> None:
    assert normalize_for_matching("a\n  b\tc") == "a b c"


def test_extraction_reviewer_rejects_quoted_false_presence_boolean() -> None:
    """A quote cannot prove that no MFN clause exists anywhere."""
    reviewer = review_cla_extraction(DOC_TEXT)
    extraction = _minimal_extraction(
        mfn_clause={"value": False, "quote": "Convertible Loan Agreement"}
    )
    extraction["missing_terms"] = [
        entry
        for entry in extraction["missing_terms"]
        if entry["term"] != "mfn_clause"
    ]
    assert any(
        "mfn_clause" in problem for problem in reviewer(extraction).problems
    )


def test_extraction_reviewer_accepts_quoted_false_property_boolean() -> None:
    """A verified quote may evidence a property like voluntary conversion."""
    reviewer = review_cla_extraction(DOC_TEXT)
    extraction = _minimal_extraction(
        qefr_mandatory={"value": False, "quote": "Convertible Loan Agreement"}
    )
    assert not reviewer(extraction).problems

"""Tests for the captable_build slice-1 stages (no LLM calls)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.captable.classification import (
    DOCUMENT_CLASSES,
    _review_classification,
    _specialized_schema,
)
from lib.captable.cla_extraction import review_cla_extraction
from lib.captable.cla_terms import build_cla_schema
from lib.captable.documents import normalize_for_matching
from lib.infrastructure.ai_text_generation.json import validate_schema

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "captable_build"


def _load(name: str) -> dict:
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


# The extraction schema is generated from the team-editable term
# checklist (config/captable_build/cla_terms.md) at runtime.
_BUILT = build_cla_schema(
    {
        "cla_terms": (CONFIG_DIR / "cla_terms.md").read_text(
            encoding="utf-8"
        ),
        "cla_extraction_base_schema": _load(
            "cla_extraction_base_schema.json"
        ),
    }
)


def _reviewer(document_text: str):
    return review_cla_extraction(
        document_text, _BUILT["quoted_fields"], _BUILT["presence_fields"]
    )


def test_classification_schema_is_valid() -> None:
    validate_schema(_load("classification_response_schema.json"))


def test_cla_extraction_schema_is_valid() -> None:
    validate_schema(_BUILT["schema"])


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
        "coc_repayment_multiple": quoted_null,
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
        "conversion_capital_sources": {"value": [], "quote": None},
        "shareholder_consents_referenced": quoted_null,
        "sha_accession_required": quoted_null,
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
            or entry.get("value") == []
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
    reviewer = _reviewer(DOC_TEXT)
    assert not reviewer(_minimal_extraction()).problems


def test_extraction_reviewer_accepts_real_quote() -> None:
    reviewer = _reviewer(DOC_TEXT)
    extraction = _minimal_extraction(
        valuation_cap={
            "value": 5000000,
            "quote": "valuation cap shall be  CHF 5,000,000",
        }
    )
    assert not reviewer(extraction).problems


def test_extraction_reviewer_rejects_fabricated_quote() -> None:
    reviewer = _reviewer(DOC_TEXT)
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
    reviewer = _reviewer(DOC_TEXT)
    extraction = _minimal_extraction(
        discount_pct={"value": 20, "quote": None}
    )
    assert any(
        "requires a verbatim quote" in problem
        for problem in reviewer(extraction).problems
    )


def test_extraction_reviewer_rejects_uncovered_absence() -> None:
    reviewer = _reviewer(DOC_TEXT)
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


def test_normalize_for_matching_is_robust_to_ocr_and_markdown() -> None:
    assert normalize_for_matching("a\n  b\tc") == "abc"
    # markdown table pipes dropped by the model when quoting
    doc = normalize_for_matching("| Initial Lenders | Helvetia Growth AG |")
    assert normalize_for_matching("Initial Lenders Helvetia Growth AG") in doc
    # OCR intra-word spacing
    doc = normalize_for_matching("E m i l W e g")
    assert normalize_for_matching("Emil Weg") in doc


def test_extraction_reviewer_rejects_quoted_false_presence_boolean() -> None:
    """A quote cannot prove that no MFN clause exists anywhere."""
    reviewer = _reviewer(DOC_TEXT)
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
    reviewer = _reviewer(DOC_TEXT)
    extraction = _minimal_extraction(
        qefr_mandatory={"value": False, "quote": "Convertible Loan Agreement"}
    )
    assert not reviewer(extraction).problems


def test_quoted_fields_cover_schema() -> None:
    """Every {value, quote}-shaped top-level property must be reviewed."""
    quoted_shape = set()
    for name, prop in _BUILT["schema"]["properties"].items():
        ref = prop.get("$ref", "")
        keys = set(prop.get("properties", {}))
        if ref.startswith("#/$defs/quoted_") or keys == {"value", "quote"}:
            quoted_shape.add(name)
    assert quoted_shape == set(_BUILT["quoted_fields"]), (
        f"schema/reviewer drift: only_in_schema="
        f"{sorted(quoted_shape - set(_BUILT['quoted_fields']))}, "
        f"only_in_reviewer="
        f"{sorted(set(_BUILT['quoted_fields']) - quoted_shape)}"
    )
    assert _BUILT["presence_fields"] <= quoted_shape


def test_extraction_reviewer_accepts_ellipsis_split_quote() -> None:
    reviewer = _reviewer(DOC_TEXT)
    extraction = _minimal_extraction(
        valuation_cap={
            "value": 5000000,
            "quote": "The valuation cap ... CHF 5,000,000",
        }
    )
    assert not reviewer(extraction).problems


# --- Work-product freshness (review point 2 on PR #61) ----------------------


def _captable_extraction(document: str) -> dict:
    return {
        "document": document,
        "as_of_date": {"value": "2026-06-30", "quote": "as of 30 June 2026"},
        "share_classes": [
            {"id": "common", "name": "Common", "nominal_value": 0.10,
             "votes_per_share": 1, "quote": "Common 0.10 1"},
        ],
        "stakeholders": [
            {"name": "Founder", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 900_000}],
             "diluted_count": 900_000, "invested_amount": 90_000,
             "group": None, "quote": "Founder 900,000 90,000"},
            {"name": "ESOP", "kind": "pool", "role": "employee",
             "holdings": [], "diluted_count": 100_000, "invested_amount": None,
             "group": None, "quote": "ESOP 100,000"},
        ],
        "pools": [
            {"kind": "esop", "label": "ESOP", "total": 100_000,
             "granted": 0, "unallocated": 100_000, "quote": "ESOP 100,000 0 100,000"},
        ],
        "totals": {
            "by_class": [{"class_id": "common", "issued_total": 900_000}],
            "diluted_total": 1_000_000,
            "quote": "total 900,000 / fully diluted 1,000,000",
        },
        "fully_diluted_definition": {"value": "full_pools", "quote": "fd"},
        "assumptions": [],
    }


def _install_dataset(name: str, parsed_text: str) -> None:
    from lib.datasets.paths import dataset_location_for_domain
    from lib.storage import get_storage

    storage = get_storage()
    location = dataset_location_for_domain(name, "startups")
    for rel in (location.raw_rel, location.parsed_rel, location.insights_rel):
        storage.mkdir(rel)
    storage.write_text(f"{location.raw_rel}/captable.md", parsed_text)
    storage.write_text(f"{location.parsed_rel}/captable.md", parsed_text)
    from lib.datasets.manifest import IngestionManifest
    import hashlib
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = hashlib.sha256(parsed_text.encode()).hexdigest()
    manifest.save()


def _patched_build(monkeypatch):
    """The build pipeline with counting fakes at the two LLM boundaries."""
    import lib.captable.table_extraction as table_extraction_mod
    import skills.captable_build.captable_build as build_mod

    calls = {"classify": 0, "captable": 0}

    async def fake_classify(dataset_name):
        calls["classify"] += 1
        return {
            "dataset": dataset_name,
            "documents": [
                {"filename": "captable.md",
                 "document_class": "current_cap_table", "confidence": 95,
                 "as_of_date": "2026-06-30", "language": "en",
                 "rationale": "fixture"}
            ],
        }

    async def fake_extract_captable(_dataset, filename, _text):
        calls["captable"] += 1
        return {**_captable_extraction(filename), "dataset": _dataset}

    monkeypatch.setattr(build_mod, "classify_documents", fake_classify)
    monkeypatch.setattr(
        table_extraction_mod, "extract_captable", fake_extract_captable
    )
    return build_mod, calls


def test_build_reuses_insights_only_while_fresh(mock_env, monkeypatch):
    import asyncio
    from lib.captable import insights as insight_module

    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build_mod, calls = _patched_build(monkeypatch)
    _install_dataset("freshco", "Founder 900,000")
    result = asyncio.run(build_mod.build("freshco"))
    asyncio.run(build_mod.build("freshco"))
    assert calls == {"classify": 1, "captable": 1}
    assert "freshness" not in result
    assert "freshness" not in result["aggregation"]

    # Simulate a corrected source and its newly indexed revision.
    _install_dataset("freshco", "Founder 850,000")
    asyncio.run(build_mod.build("freshco"))
    assert calls == {"classify": 2, "captable": 2}

    real_config = insight_module.load_repository_config
    def edited_config(key):
        config = dict(real_config(key))
        config["classification_prompt"] += " Edited"
        return config
    monkeypatch.setattr(insight_module, "load_repository_config", edited_config)
    asyncio.run(build_mod.build("freshco"))
    # Unchanged selected classification content does not invalidate extraction.
    assert calls == {"classify": 3, "captable": 2}
    asyncio.run(build_mod.build("freshco"))
    assert calls == {"classify": 3, "captable": 2}

    # Model selection follows the shared ranked-model policy.
    monkeypatch.setenv("RANKED_LLMS", "gemini/lite-model")
    monkeypatch.setattr(insight_module, "llm_model", lambda: "gemini/lite-model")
    asyncio.run(build_mod.build("freshco"))
    assert calls == {"classify": 4, "captable": 3}
    asyncio.run(build_mod.build("freshco", fresh=True))
    assert calls == {"classify": 5, "captable": 4}


def test_standalone_stages_reject_missing_freshness_metadata(mock_env, monkeypatch):
    import asyncio
    from lib.captable.insights import build_insight
    from lib.storage import get_storage

    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build_mod, calls = _patched_build(monkeypatch)
    _install_dataset("stale-co", "Founder 900,000")
    asyncio.run(build_mod.build("stale-co"))
    insight = build_insight("stale-co", "classification")
    get_storage().remove(insight._manifest_path)
    asyncio.run(build_mod.table("stale-co"))
    assert calls == {"classify": 2, "captable": 2}


def _complete_cla(dataset="fixture", **overrides):
    """Full stored CLA fixture; keep domain-review fixtures independently sparse."""
    from copy import deepcopy

    fields = deepcopy(_minimal_extraction())
    for name, shape in _BUILT["schema"]["properties"].items():
        if name not in fields:
            if name == "comments":
                fields[name] = None
            elif "$ref" in shape:
                fields[name] = {"value": None, "quote": None}
            else:
                value_schema = shape["properties"]["value"]
                value = [] if value_schema.get("type") == "array" else "unstated"
                fields[name] = {"value": value, "quote": None}
    fields = {key: value for key, value in fields.items() if key in _BUILT["schema"]["properties"]}
    fields.update(dataset=dataset, document="cla.md")
    fields.update(overrides)
    for value in fields.values():
        if isinstance(value, dict) and "value" in value:
            value.setdefault("quote", None)
    return fields


def _consolidated_artifact(dataset, *, captable=None, loans=None):
    from lib.captable.aggregation import aggregate_clas
    from lib.captable.data import assemble_result

    loans = loans or []
    aggregation = aggregate_clas(loans)
    aggregation["dataset"] = dataset
    return assemble_result(
        dataset, classification={"documents": []}, captable=captable,
        register=None, pool_docs=[], cla_extraction={"clas": loans, "failures": []},
        assessment={"assessments": []}, aggregation=aggregation, validation=[],
    )

"""Build structured cap-table/CLA facts for one startup dataset (issue #17).

Slice 1 implements the first two pipeline stages:
1. classify every dataset document,
2. extract the term schema from each convertible loan agreement.

Later slices add the qualitative checklist, aggregation, cap-table
extraction, code validation, and the versioned snapshot store.
"""

from __future__ import annotations

import json
from typing import Any

from lib.captable.classification import CLA_CLASSES, classify_documents
from lib.captable.cla_extraction import extract_cla
from lib.captable.documents import load_parsed_documents
from lib.datasets.paths import dataset_insights_path
from lib.infrastructure.logging import get_logger
from lib.storage import get_storage

logger = get_logger(__name__)

_WORK_DIR = "captable/work"


def _work_path(dataset_name: str, name: str) -> str:
    insights_rel = dataset_insights_path(dataset_name)
    return f"{insights_rel}/{_WORK_DIR}/{name}"


def _store_work(dataset_name: str, name: str, payload: Any) -> str:
    storage = get_storage()
    rel = _work_path(dataset_name, name)
    parent = rel.rsplit("/", 1)[0]
    storage.mkdir(parent)
    storage.write_text(rel, json.dumps(payload, ensure_ascii=False, indent=2))
    return rel


async def classify(dataset_name: str) -> dict[str, Any]:
    """Stage 1: classify the dataset's documents; persist the result."""
    result = await classify_documents(dataset_name)
    rel = _store_work(dataset_name, "classification.json", result)
    logger.info("[%s] Stored document classification at %s", dataset_name, rel)
    return result


async def extract(dataset_name: str) -> dict[str, Any]:
    """Stage 2: extract terms from every classified CLA; persist the result.

    Runs (or reuses) the classification to find CLA documents, then extracts
    each one. Term sheets are extracted too but kept distinct via ``status``.
    """
    storage = get_storage()
    classification_rel = _work_path(dataset_name, "classification.json")
    if storage.exists(classification_rel):
        classification = json.loads(storage.read_text(classification_rel))
        logger.info(
            "[%s] Reusing stored classification %s",
            dataset_name,
            classification_rel,
        )
    else:
        classification = await classify(dataset_name)

    cla_filenames = [
        entry["filename"]
        for entry in classification["documents"]
        if entry["document_class"] in CLA_CLASSES
    ]
    if not cla_filenames:
        result: dict[str, Any] = {
            "dataset": dataset_name,
            "clas": [],
            "note": "No convertible loan documents were classified.",
        }
        _store_work(dataset_name, "cla_extraction.json", result)
        return result

    texts = {
        document.filename: document.text
        for document in load_parsed_documents(dataset_name)
    }
    extractions = []
    failures = []
    for filename in cla_filenames:
        if filename not in texts:
            raise ValueError(
                f"Classified CLA {filename!r} has no parsed text."
            )
        logger.info("[%s] Extracting CLA terms from %r", dataset_name, filename)
        try:
            extractions.append(
                await extract_cla(dataset_name, filename, texts[filename])
            )
        except Exception as error:  # one bad document must not sink the corpus
            logger.error(
                "[%s] CLA extraction failed for %r: %s",
                dataset_name,
                filename,
                error,
            )
            failures.append({"document": filename, "error": str(error)})

    result = {"dataset": dataset_name, "clas": extractions, "failures": failures}
    rel = _store_work(dataset_name, "cla_extraction.json", result)
    logger.info("[%s] Stored CLA extraction at %s", dataset_name, rel)
    return result


def _load_work(dataset_name: str, name: str) -> Any | None:
    storage = get_storage()
    rel = _work_path(dataset_name, name)
    if storage.exists(rel):
        return json.loads(storage.read_text(rel))
    return None


async def _extraction_or_run(dataset_name: str) -> dict[str, Any]:
    stored = _load_work(dataset_name, "cla_extraction.json")
    if stored is not None:
        return stored
    return await extract(dataset_name)


async def assess(dataset_name: str) -> dict[str, Any]:
    """Stage 3: deterministically assess every extracted CLA."""
    from lib.captable.assessment import assess_cla, worst_severity
    from lib.infrastructure.configuration import load_repository_config

    rules = load_repository_config("captable")["assessment_rules"]
    extraction = await _extraction_or_run(dataset_name)
    assessments = []
    for cla in extraction["clas"]:
        findings = assess_cla(cla, rules)
        assessments.append(
            {
                "document": cla["document"],
                "status": cla.get("status"),
                "worst_severity": worst_severity(findings),
                "findings": findings,
            }
        )
    result = {"dataset": dataset_name, "assessments": assessments}
    rel = _store_work(dataset_name, "assessment.json", result)
    logger.info("[%s] Stored CLA assessment at %s", dataset_name, rel)
    return result


async def aggregate(dataset_name: str) -> dict[str, Any]:
    """Stage 4: aggregate all extracted CLAs of the dataset."""
    from lib.captable.aggregation import aggregate_clas
    from lib.captable.esign import scan_esign_markers
    from lib.datasets.paths import dataset_raw_path

    extraction = await _extraction_or_run(dataset_name)
    storage = get_storage()
    raw_rel = dataset_raw_path(dataset_name)
    markers: dict[str, dict] = {}
    for cla in extraction["clas"]:
        document = cla["document"]
        pdf_rel = f"{raw_rel}/{document}"
        if document.lower().endswith(".pdf") and storage.exists(pdf_rel):
            markers[document] = scan_esign_markers(storage.read_bytes(pdf_rel))
    result = aggregate_clas(extraction["clas"], esign_markers=markers)
    result["dataset"] = dataset_name
    rel = _store_work(dataset_name, "aggregation.json", result)
    logger.info("[%s] Stored CLA aggregation at %s", dataset_name, rel)
    return result

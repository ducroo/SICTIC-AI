"""Build four managed JSON insights for a startup's capitalization data."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from lib.captable.classification import CLA_CLASSES, classify_documents
from lib.captable.cla_extraction import extract_cla
from lib.captable.documents import load_parsed_documents
from lib.captable.data import assemble_result
from lib.captable.insights import build_insight, configured_build_insight, read_build_insight
from lib.captable.assessment import assess_cla, worst_severity
from lib.captable.aggregation import aggregate_clas
from lib.captable.esign import scan_esign_markers
from lib.captable.validate import validate_captable
from lib.datasets.paths import dataset_raw_path
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.storage import get_storage

logger = get_logger(__name__)


def _manual(insight: InsightFile) -> InsightFile | None:
    preferred = insight.find(selection="any")
    return preferred if preferred is not None and preferred.model == "manual" else None


def _reusable(insight: InsightFile, fresh: bool) -> InsightFile | None:
    return _manual(insight) if fresh else insight.find(selection="reusable")


def _save(insight: InsightFile, data: dict) -> InsightFile:
    insight.save(json.dumps(data, ensure_ascii=False, indent=2))
    return insight


def _config(*keys: str) -> dict:
    config = load_repository_config("captable_build")
    return {key: config[key] for key in keys}


async def _classification(dataset_name: str, *, fresh: bool = False) -> InsightFile:
    insight = configured_build_insight(dataset_name, "classification")
    if existing := _reusable(insight, fresh):
        read_build_insight(existing)
        return existing
    return _save(insight, await classify_documents(dataset_name))


async def _loans(dataset_name: str, classification: InsightFile, *, fresh: bool = False) -> InsightFile:
    insight = configured_build_insight(dataset_name, "loan-extraction", classification)
    if existing := _reusable(insight, fresh):
        read_build_insight(existing)
        return existing
    documents = read_build_insight(classification)["documents"]
    filenames = [entry["filename"] for entry in documents if entry["document_class"] in CLA_CLASSES]
    texts = {doc.filename: doc.text for doc in load_parsed_documents(dataset_name)}
    missing = [name for name in filenames if name not in texts]
    if missing:
        raise ValueError(f"Classified CLA documents have no parsed text: {missing}")
    outcomes = await asyncio.gather(*(extract_cla(dataset_name, name, texts[name]) for name in filenames), return_exceptions=True)
    for name, outcome in zip(filenames, outcomes):
        if isinstance(outcome, BaseException):
            logger.error("[%s] CLA extraction failed for %s: %s", dataset_name, name, outcome)
            raise ValueError(f"CLA extraction incomplete: {name}. Re-run to retry extraction.") from outcome
    return _save(insight, {"dataset": dataset_name, "clas": outcomes, "failures": []})


async def _tables(dataset_name: str, classification_insight: InsightFile, *, fresh: bool = False) -> InsightFile:
    from lib.captable.table_extraction import extract_captable, extract_pools, extract_register

    insight = configured_build_insight(dataset_name, "table-extraction", classification_insight)
    if existing := _reusable(insight, fresh):
        read_build_insight(existing)
        return existing
    classification = read_build_insight(classification_insight)
    def latest_of(document_class: str) -> str | None:
        from lib.captable.data import normalize_iso_date

        candidates = [
            entry
            for entry in classification["documents"]
            if entry["document_class"] == document_class
        ]
        if not candidates:
            return None

        def sort_key(entry):
            normalized = normalize_iso_date(entry.get("as_of_date")) or ""
            # ISO strings sort correctly; unparseable dates rank last so a
            # dated document always beats an undatable one.
            import re
            is_iso = bool(re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", normalized))
            return (is_iso, normalized if is_iso else "")

        return max(candidates, key=sort_key)["filename"]

    texts = {
        document.filename: document.text
        for document in load_parsed_documents(dataset_name)
    }
    missing = [entry["filename"] for entry in classification["documents"]
               if entry["document_class"] in {"current_cap_table", "share_register", "esop_psop_plan"}
               and entry["filename"] not in texts]
    if missing:
        raise ValueError(f"Classified table documents have no parsed text: {missing}")
    result: dict[str, Any] = {
        "dataset": dataset_name,
        "captable": None,
        "captable_versions": [],
        "register": None,
        "pool_documents": [],
        "failures": [],
    }

    jobs: list[tuple[str, str, Any]] = []
    # Extract EVERY cap-table version: registers/pool docs are reconciled
    # against the version nearest their own date, and older versions are
    # historical states in their own right (design §2.3).
    for entry in classification["documents"]:
        if entry["document_class"] != "current_cap_table":
            continue
        filename = entry["filename"]
        if filename in texts:
            jobs.append(
                ("captable_version", filename,
                 extract_captable(dataset_name, filename, texts[filename]))
            )
    register_doc = latest_of("share_register")
    if register_doc and register_doc in texts:
        jobs.append(
            ("register", register_doc,
             extract_register(dataset_name, register_doc, texts[register_doc]))
        )
    for entry in classification["documents"]:
        if entry["document_class"] != "esop_psop_plan":
            continue
        filename = entry["filename"]
        if filename in texts:
            jobs.append(
                ("pool", filename,
                 extract_pools(dataset_name, filename, texts[filename]))
            )
    outcomes = await asyncio.gather(
        *(coro for _slot, _doc, coro in jobs), return_exceptions=True
    )
    first_failure = None
    for (slot, document, _coro), outcome in zip(jobs, outcomes):
        if isinstance(outcome, BaseException):
            first_failure = first_failure or outcome
            result["failures"].append(
                {"document": document, "error": str(outcome)}
            )
        elif slot == "pool":
            result["pool_documents"].append(outcome)
        elif slot == "captable_version":
            result["captable_versions"].append(outcome)
        else:
            result[slot] = outcome

    def version_date(version: dict[str, Any]) -> str:
        from lib.captable.data import normalize_iso_date

        stated = (version.get("as_of_date") or {}).get("value")
        return normalize_iso_date(stated) or ""

    if result["captable_versions"]:
        result["captable"] = max(
            result["captable_versions"], key=version_date
        )

    if result["failures"]:
        raise ValueError(f"Table extraction incomplete: {[f['document'] for f in result['failures']]}. Re-run to retry extraction.") from first_failure
    return _save(insight, result)


def _assessment(dataset_name: str, extraction: dict, rules: dict) -> dict:
    assessments = []
    for cla in extraction["clas"]:
        findings = assess_cla(cla, rules)
        assessments.append({"document": cla["document"], "status": cla.get("status"), "worst_severity": worst_severity(findings), "findings": findings})
    return {"dataset": dataset_name, "assessments": assessments}


def _aggregation(dataset_name: str, extraction: dict, rules: dict) -> dict:
    storage = get_storage()
    raw_rel = dataset_raw_path(dataset_name)
    markers = {}
    for cla in extraction["clas"]:
        document = cla["document"]
        path = f"{raw_rel}/{document}"
        if document.lower().endswith(".pdf") and storage.exists(path):
            markers[document] = scan_esign_markers(storage.read_bytes(path))
    result = aggregate_clas(extraction["clas"], esign_markers=markers,
        conversion_window_days=int(rules["maturity_conversion_window_days"]))
    result["dataset"] = dataset_name
    return result


def _consolidate(dataset_name: str, classification: dict, tables: dict, cla_extraction: dict, rules: dict) -> dict:
    assessment = _assessment(dataset_name, cla_extraction, rules)
    aggregation = _aggregation(dataset_name, cla_extraction, rules)
    captable = tables.get("captable")
    captable_versions = tables.get("captable_versions") or (
        [captable] if captable else []
    )
    register = tables.get("register")
    pool_docs = tables.get("pool_documents", [])
    extraction_failures = list(tables.get("failures", []))
    if captable is None:
        extraction_failures.append(
            {
                "document": None,
                "error": "No current cap table was extracted (none "
                "classified, or extraction failed) — ownership sections "
                "of this result are EMPTY, not clean.",
            }
        )
    from lib.captable.data import normalize_iso_date

    def _months(iso: str) -> int | None:
        if len(iso) >= 7:
            return int(iso[:4]) * 12 + int(iso[5:7])
        if len(iso) == 4:
            return int(iso) * 12 + 6  # year-only: assume mid-year
        return None

    def nearest_version(source: dict | None) -> dict | None:
        """Cap-table version dated nearest the source document's as-of."""
        if not source or not captable_versions:
            return None
        entry = source.get("as_of_date")
        target = normalize_iso_date(
            entry.get("value") if isinstance(entry, dict) else entry
        )
        target_months = _months(target) if target else None
        if target_months is None:
            return None
        candidates = []
        for version in captable_versions:
            version_iso = normalize_iso_date(
                (version.get("as_of_date") or {}).get("value")
            )
            version_months = _months(version_iso) if version_iso else None
            if version_months is not None:
                candidates.append(
                    (abs(version_months - target_months), version)
                )
        if not candidates:
            return None
        return min(candidates, key=lambda pair: pair[0])[1]

    validation = validate_captable(
        captable or {},
        register=register,
        pool_docs=pool_docs,
        clas=cla_extraction.get("clas", []),
        register_captable=nearest_version(register),
        pool_captable=nearest_version(pool_docs[0] if pool_docs else None),
    )

    if extraction_failures:
        validation = [
            {
                "check": "table_extraction",
                "status": "fail",
                "severity": "severe",
                "detail": failure["error"]
                if failure.get("document") is None
                else f"{failure['document']}: {failure['error'][:160]}",
            }
            for failure in extraction_failures
        ] + validation

    result = assemble_result(
        dataset_name,
        classification=classification,
        captable=captable,
        register=register,
        pool_docs=pool_docs,
        cla_extraction=cla_extraction,
        assessment=assessment,
        aggregation=aggregation,
        validation=validation,
    )

    return result


async def captable_build(dataset_name: str, *, fresh: bool = False) -> list[InsightFile]:
    """Select/build the consolidated JSON; at most four logical artifacts."""
    insight = build_insight(dataset_name, "consolidated")
    if manual := _manual(insight):
        read_build_insight(manual)
        return [manual]
    classification = await _classification(dataset_name, fresh=fresh)
    loans = await _loans(dataset_name, classification, fresh=fresh)
    tables = await _tables(dataset_name, classification, fresh=fresh)
    rules = _config("assessment_rules")["assessment_rules"]
    insight = configured_build_insight(dataset_name, "consolidated", classification, loans, tables)
    if existing := _reusable(insight, fresh):
        read_build_insight(existing)
        return [existing]
    result = _consolidate(dataset_name, read_build_insight(classification),
        read_build_insight(tables), read_build_insight(loans), rules)
    return [_save(insight, result)]


# Explicit structured adapters share the same managed stage implementations.
async def build(dataset_name: str, *, fresh: bool = False) -> dict[str, Any]:
    [insight] = await captable_build(dataset_name, fresh=fresh)
    return read_build_insight(insight)


async def classify(dataset_name: str) -> dict[str, Any]:
    return read_build_insight(await _classification(dataset_name))


async def extract(dataset_name: str) -> dict[str, Any]:
    return read_build_insight(await _loans(dataset_name, await _classification(dataset_name)))


async def table(dataset_name: str) -> dict[str, Any]:
    return read_build_insight(await _tables(dataset_name, await _classification(dataset_name)))


async def assess(dataset_name: str) -> dict[str, Any]:
    return _assessment(dataset_name, await extract(dataset_name), _config("assessment_rules")["assessment_rules"])


async def aggregate(dataset_name: str) -> dict[str, Any]:
    return _aggregation(dataset_name, await extract(dataset_name), _config("assessment_rules")["assessment_rules"])

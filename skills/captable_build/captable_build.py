"""Build structured cap-table/CLA facts for one startup dataset (issue #17).

Seven pipeline stages (see docs/captable.md for the architecture):
1. classify every dataset document,
2. extract the term schema from every convertible loan agreement,
3. assess each CLA deterministically against market-standard bands,
4. aggregate CLAs (identical-terms grouping, 10/20 non-bank counts),
5. extract cap-table versions, the share register, and pool overviews,
6. validate everything in code (totals, reconciliations, lifecycle),
7. store the versioned snapshot under insights/captable/snapshots/.

The LLM finds, classifies, and extracts values with verified verbatim
quotes; every calculation and consistency judgment is plain Python.
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
    for filename in cla_filenames:
        if filename not in texts:
            raise ValueError(
                f"Classified CLA {filename!r} has no parsed text."
            )
    import asyncio

    logger.info(
        "[%s] Extracting CLA terms from %d documents in parallel",
        dataset_name,
        len(cla_filenames),
    )
    outcomes = await asyncio.gather(
        *(
            extract_cla(dataset_name, filename, texts[filename])
            for filename in cla_filenames
        ),
        return_exceptions=True,
    )
    extractions = []
    failures = []
    for filename, outcome in zip(cla_filenames, outcomes):
        if isinstance(outcome, BaseException):
            # one bad document must not sink the corpus
            logger.error(
                "[%s] CLA extraction failed for %r: %s",
                dataset_name,
                filename,
                outcome,
            )
            failures.append({"document": filename, "error": str(outcome)})
        else:
            extractions.append(outcome)

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


async def table(dataset_name: str) -> dict[str, Any]:
    """Stage 5: extract cap table, share register, and pool documents."""
    from lib.captable.table_extraction import (
        extract_captable,
        extract_pools,
        extract_register,
    )

    storage = get_storage()
    classification_rel = _work_path(dataset_name, "classification.json")
    if storage.exists(classification_rel):
        classification = json.loads(storage.read_text(classification_rel))
    else:
        classification = await classify(dataset_name)

    def latest_of(document_class: str) -> str | None:
        from lib.captable.snapshot import normalize_iso_date

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
    result: dict[str, Any] = {
        "dataset": dataset_name,
        "captable": None,
        "captable_versions": [],
        "register": None,
        "pool_documents": [],
        "failures": [],
    }

    import asyncio

    jobs: list[tuple[str, str, Any]] = []
    captable_doc = latest_of("current_cap_table")
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
    del captable_doc  # resolved after gathering, from the versions list
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
    for (slot, document, _coro), outcome in zip(jobs, outcomes):
        if isinstance(outcome, BaseException):
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
        from lib.captable.snapshot import normalize_iso_date

        stated = (version.get("as_of_date") or {}).get("value")
        return normalize_iso_date(stated) or ""

    if result["captable_versions"]:
        result["captable"] = max(
            result["captable_versions"], key=version_date
        )

    rel = _store_work(dataset_name, "table_extraction.json", result)
    logger.info("[%s] Stored table extraction at %s", dataset_name, rel)
    return result


async def snapshot(dataset_name: str) -> dict[str, Any]:
    """Stages 6+7: validate, assemble, and store the versioned snapshot."""
    from lib.captable.snapshot import assemble_snapshot, render_markdown
    from lib.captable.validate import check_cross_snapshot, validate_captable
    from lib.datasets.paths import dataset_insights_path

    storage = get_storage()
    classification = _load_work(dataset_name, "classification.json")
    tables = _load_work(dataset_name, "table_extraction.json")
    cla_extraction = _load_work(dataset_name, "cla_extraction.json")
    assessment = _load_work(dataset_name, "assessment.json")
    aggregation = _load_work(dataset_name, "aggregation.json")
    missing = [
        name
        for name, value in (
            ("classification", classification),
            ("table_extraction", tables),
            ("cla_extraction", cla_extraction),
            ("assessment", assessment),
            ("aggregation", aggregation),
        )
        if value is None
    ]
    if missing:
        raise ValueError(
            f"Missing work products {missing}; run the earlier stages "
            "(or `build`) first."
        )

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
                "of this snapshot are EMPTY, not clean.",
            }
        )
    from lib.captable.snapshot import normalize_iso_date

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

    snap = assemble_snapshot(
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

    insights_rel = dataset_insights_path(dataset_name)
    snapshots_dir = f"{insights_rel}/captable/snapshots"
    storage.mkdir(snapshots_dir)
    # Cross-snapshot checks against the previous version of this as-of state
    # and the latest older state, when they exist.
    # The snapshot filename must be a single flat path segment.
    safe_as_of = str(snap["as_of_date"]).replace("/", "-").replace("\\", "-")
    older_rels = sorted(
        rel
        for rel in storage.list(snapshots_dir, suffix=".json")
        if rel != f"{safe_as_of}.json" and rel[:-5] < safe_as_of
    )
    if older_rels:
        previous = json.loads(
            storage.read_text(f"{snapshots_dir}/{older_rels[-1]}")
        )
        snap["validation"] = snap["validation"] + check_cross_snapshot(
            previous, snap
        )

    payload = json.dumps(snap, ensure_ascii=False, indent=2)
    storage.write_text(f"{snapshots_dir}/{safe_as_of}.json", payload)
    newer_exists = any(
        rel[:-5] > safe_as_of
        for rel in storage.list(snapshots_dir, suffix=".json")
        if rel != f"{safe_as_of}.json"
    )
    if not newer_exists:
        from lib.captable.render_html import render_html

        storage.write_text(f"{insights_rel}/captable/latest.json", payload)
        storage.write_text(
            f"{insights_rel}/captable/captable.md", render_markdown(snap)
        )
        storage.write_text(
            f"{insights_rel}/captable/captable.html", render_html(snap)
        )
    else:
        logger.warning(
            "[%s] A newer snapshot exists; latest.json left untouched.",
            dataset_name,
        )
    logger.info(
        "[%s] Stored snapshot %s and captable.md",
        dataset_name,
        snap["as_of_date"],
    )
    return snap


async def build(dataset_name: str, *, fresh: bool = False) -> dict[str, Any]:
    """Run the full pipeline (stages 1-7), reusing stored work products.

    With ``fresh=True`` all stored work products are discarded first.
    """
    storage = get_storage()
    if fresh:
        for name in (
            "classification.json",
            "cla_extraction.json",
            "assessment.json",
            "aggregation.json",
            "table_extraction.json",
        ):
            rel = _work_path(dataset_name, name)
            if storage.exists(rel):
                storage.remove(rel)

    if _load_work(dataset_name, "classification.json") is None:
        await classify(dataset_name)
    if _load_work(dataset_name, "cla_extraction.json") is None:
        await extract(dataset_name)
    await assess(dataset_name)
    await aggregate(dataset_name)
    if _load_work(dataset_name, "table_extraction.json") is None:
        await table(dataset_name)
    return await snapshot(dataset_name)


async def aggregate(dataset_name: str) -> dict[str, Any]:
    """Stage 4: aggregate all extracted CLAs of the dataset."""
    from lib.captable.aggregation import aggregate_clas
    from lib.captable.esign import scan_esign_markers
    from lib.datasets.paths import dataset_raw_path

    extraction = await _extraction_or_run(dataset_name)
    storage = get_storage()
    raw_rel = dataset_raw_path(dataset_name)
    cache = _load_work(dataset_name, "esign_markers.json") or {}
    markers: dict[str, dict] = {}
    cache_dirty = False
    for cla in extraction["clas"]:
        document = cla["document"]
        pdf_rel = f"{raw_rel}/{document}"
        if not document.lower().endswith(".pdf") or not storage.exists(pdf_rel):
            continue
        cached = cache.get(document)
        # cache key: file size (cheap, stable for our immutable data rooms;
        # the saving is skipping the zlib stream scan, not the read)
        pdf_bytes = storage.read_bytes(pdf_rel)
        if cached and cached.get("size") == len(pdf_bytes):
            markers[document] = cached["markers"]
            continue
        markers[document] = scan_esign_markers(pdf_bytes)
        cache[document] = {
            "size": len(pdf_bytes),
            "markers": markers[document],
        }
        cache_dirty = True
    if cache_dirty:
        _store_work(dataset_name, "esign_markers.json", cache)
    from lib.infrastructure.configuration import load_repository_config

    rules = load_repository_config("captable")["assessment_rules"]
    result = aggregate_clas(
        extraction["clas"],
        esign_markers=markers,
        conversion_window_days=int(
            rules.get("maturity_conversion_window_days", 30)
        ),
    )
    result["dataset"] = dataset_name
    rel = _store_work(dataset_name, "aggregation.json", result)
    logger.info("[%s] Stored CLA aggregation at %s", dataset_name, rel)
    return result

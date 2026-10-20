"""Sweep pending company research, then acquire one dossier's report once."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.ai_text_generation.json import validate_json_schema
from lib.infrastructure.companyresearch import CompanyResearchAdapter, CompanyResearchError
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.filesystem import replace_directory_snapshot
from lib.infrastructure.logging import get_logger
from lib.insights.locking import atomic_write, manifest_write_lock
from lib.startups.identity import canonical_startup_slug
from lib.storage import get_storage
from .identity import normalize_uid, resolve_uid

logger = get_logger(__name__)
REGISTRY = "cache/import_companyresearch/requests.json"
TERMINAL = {"failed", "cancelled", "expired"}


@dataclass(frozen=True)
class CompanyResearchImportResult:
    startup: str
    uid: str
    status: str
    report_path: str | None = None
    request_id: str | None = None
    error: str | None = None


def _root(startup):
    return f"{dataset_location_for_domain(startup, 'startups').raw_rel}/companyresearch-ch"


def _completed(storage, startup):
    return all(storage.exists(f"{_root(startup)}/{name}") for name in ("report.json", "report.md"))


def _result(storage, startup, entry, *, status=None, error=None):
    return CompanyResearchImportResult(
        startup, entry["uid"], status or entry["status"],
        str(storage.local_path(f"{_root(startup)}/report.md")) if _completed(storage, startup) else None,
        entry.get("request_id"), error,
    )


def _render(report):
    """Lossless deterministic rendering of provider fields, including evidence IDs."""
    def label(key):
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).replace("_", " ").capitalize()

    def lines(value, depth=0):
        indent = "  " * depth
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (dict, list)) and item:
                    yield f"{indent}- **{label(key)}:**"
                    yield from lines(item, depth + 1)
                else:
                    yield f"{indent}- **{label(key)}:** {scalar(item)}"
        elif isinstance(value, list):
            for i, item in enumerate(value, 1):
                if isinstance(item, (dict, list)):
                    yield f"{indent}- **Item {i}:**"
                    yield from lines(item, depth + 1)
                else:
                    yield f"{indent}- {scalar(item)}"

    def scalar(value):
        if value is None:
            return "Not reported"
        if value == [] or value == {}:
            return "None reported"
        return str(value).replace("\n", "\n\n")

    output = [f"# CompanyResearch: {report['companyIdentity']['legalName']}", "",
              "Source: https://companyresearch.ch/", ""]
    for key, value in report.items():
        output.extend([f"## {label(key)}", ""])
        output.extend(lines(value) if isinstance(value, (dict, list)) else [scalar(value)])
        output.append("")
    return "\n".join(output)


def _publish(storage, startup, report):
    target = Path(storage.local_path(_root(startup)))
    target.parent.mkdir(parents=True, exist_ok=True)
    # Sibling staging keeps publication atomic on the destination filesystem.
    with tempfile.TemporaryDirectory(prefix=".companyresearch-staging-", dir=target.parent) as temp:
        staging = Path(temp) / "snapshot"
        staging.mkdir()
        (staging / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "report.md").write_text(_render(report), encoding="utf-8")
        replace_directory_snapshot(staging, target)


async def _advance(startup, entry, adapter, storage, save):
    if _completed(storage, startup):
        entry["status"] = "imported"
        save()
        return _result(storage, startup, entry)
    if entry.get("request_id"):
        receipt = await adapter.receipt(entry["request_id"])
    else:
        entry["status"] = "submitting"
        save()  # An interrupted POST must retry with the same idempotency key.
        receipt = await adapter.submit(entry["uid"], entry["idempotency_key"])
    if receipt["companyUid"] != entry["uid"]:
        raise ValueError(f"{startup}: receipt UID differs from requested UID")
    if entry.get("request_id") and receipt["requestId"] != entry["request_id"]:
        raise ValueError(f"{startup}: receipt request ID changed")
    entry.update(request_id=receipt["requestId"], status=receipt["status"])
    save()  # Receipt survives failed report downloads or publication.
    if receipt["status"] == "succeeded":
        if not receipt.get("runId"):
            raise ValueError(f"{startup}: succeeded request has no report run ID")
        report = await adapter.report(entry["uid"], receipt["runId"])
        if report["companyIdentity"]["uid"] != entry["uid"]:
            raise ValueError(f"{startup}: report UID differs from requested UID")
        _publish(storage, startup, report)
        entry["status"] = "imported"
        save()
        logger.info("[%s] CompanyResearch report imported", startup)
    elif receipt["status"] in TERMINAL:
        entry["error"] = (receipt.get("error") or {}).get("code", receipt["status"])
        save()
        logger.error("[%s] CompanyResearch request %s: %s", startup, entry["status"], entry["error"])
    else:
        logger.info("[%s] CompanyResearch request %s; collect on the next call", startup, entry["status"])
    return _result(storage, startup, entry, error=entry.get("error"))


async def _workflow(startup, uid, company_name, storage, injected_adapter):
    config = load_repository_config("import_companyresearch")
    path = Path(storage.local_path(REGISTRY))
    registry = json.loads(path.read_text()) if path.exists() else {}
    validate_json_schema(registry, config["registry_schema"], label="CompanyResearch request registry")
    adapter = injected_adapter

    def client():
        nonlocal adapter
        if adapter is None:
            adapter = CompanyResearchAdapter()
        return adapter

    def save():
        atomic_write(path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n")

    results = {}
    new_startup = None
    try:
        # Collect ALL accepted requests before trying any held submission.
        for dossier, entry in registry.items():
            if entry["status"] in TERMINAL or (entry["status"] == "imported" and _completed(storage, dossier)):
                continue
            if not entry.get("request_id") and not _completed(storage, dossier):
                continue
            try:
                results[dossier] = await _advance(dossier, entry, client(), storage, save)
            except Exception as error:
                logger.error("[%s] CompanyResearch collection failed: %s", dossier, error)
                results[dossier] = _result(storage, dossier, entry, status="error", error=str(error))
        if startup is not None and _completed(storage, startup):
            report = json.loads(storage.read_text(f"{_root(startup)}/report.json"))
            existing_uid = report["companyIdentity"]["uid"]
            results[startup] = _result(storage, startup,
                registry.get(startup, {"uid": existing_uid, "status": "imported"}))
        elif startup is not None and startup in registry:
            # Reuse the registration; terminal outcomes remain untouched.
            if startup not in results:
                results[startup] = _result(storage, startup, registry[startup], error=registry[startup].get("error"))
        elif startup is not None:
            resolved = uid or await resolve_uid(startup, company_name, storage, client(), config)
            entry = {"uid": resolved, "idempotency_key": uuid.uuid4().hex,
                     "request_id": None, "status": "on_hold"}
            registry[startup] = entry
            save()  # Identity discovery and queue registration do not need a research slot.
            new_startup = startup

        # JSON object insertion order retains FIFO across atomic registry writes.
        # Legacy 'submitting' records remain retryable with their original keys.
        capacity_full = False
        for dossier, entry in registry.items():
            if entry.get("request_id") or entry["status"] not in ("on_hold", "submitting"):
                continue
            if capacity_full:
                results[dossier] = _result(storage, dossier, entry)
                continue
            try:
                results[dossier] = await _advance(dossier, entry, client(), storage, save)
            except Exception as error:
                if isinstance(error, CompanyResearchError) and error.concurrency_limited:
                    entry["status"] = "on_hold"
                    save()
                    capacity_full = True
                    results[dossier] = _result(storage, dossier, entry)
                    logger.info("[%s] CompanyResearch capacity full; holding submissions until the next call", dossier)
                    continue
                if dossier == new_startup:
                    raise
                logger.error("[%s] CompanyResearch submission failed: %s", dossier, error)
                results[dossier] = _result(storage, dossier, entry, status="error", error=str(error))
        return list(results.values())
    finally:
        if adapter is not None and injected_adapter is None:
            adapter.close()


def _locked(startup, uid, company_name, storage, adapter):
    # Run the lock and the entire workflow in a worker: competing async callers
    # must not block the caller event loop while waiting for the filesystem lock.
    with manifest_write_lock(Path(storage.local_path(REGISTRY))):
        return asyncio.run(_workflow(startup, uid, company_name, storage, adapter))


async def import_companyresearch(
    startup: str | None = None, *, uid: str | None = None,
    company_name: str | None = None, storage=None, adapter=None,
) -> list[CompanyResearchImportResult]:
    """Sweep once; optionally submit a startup. Return operational results, not insights."""
    if startup is None and (uid is not None or company_name is not None):
        raise ValueError("uid/company_name requires a destination startup")
    if startup is not None:
        startup = canonical_startup_slug(startup)
        if not startup:
            raise ValueError("A nonempty startup name is required")
    if uid is not None:
        uid = normalize_uid(uid)
    return await asyncio.to_thread(_locked, startup, uid, company_name, storage or get_storage(), adapter)

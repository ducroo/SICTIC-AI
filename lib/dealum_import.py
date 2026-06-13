from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from lib.adapters.dealum import DealumAdapter, DealumFileLink
from lib.logger import get_logger
from lib.slugify import slugify
from lib.startup_dossier import canonical_startup_slug, ensure_startup_dossier
from lib.storage import get_storage
from lib.storage_domains import (
    dataset_raw_path,
    dataset_location_for_domain,
)

logger = get_logger(__name__)

DEALUM_SUBDIR = "dealum"
APPLICATION_MD = "application.md"
APPLICATION_RAW_JSON = "application.raw.json"
MANIFEST_JSON = "manifest.json"
DEALUM_APP_URL = "https://app.dealum.com/#/dealroom/{dealroom_id}?application={application_id}"


@dataclass(frozen=True)
class DealumImportResult:
    startup: str
    dataset_slug: str
    imported: bool
    changed: bool
    application_found: bool
    dealum_name: Optional[str] = None
    dealum_id: Any = None
    dealum_url: Optional[str] = None
    application_code: Optional[str] = None
    match_method: Optional[str] = None
    manifest_path: Optional[str] = None
    application_path: Optional[str] = None
    downloaded_files: int = 0
    skipped_files: int = 0
    stale_files: int = 0
    step: Optional[str] = None


@dataclass(frozen=True)
class DealumMatch:
    requested_startup: str
    matched_name: str
    dataset_slug: str
    dealum_id: Any
    dealum_url: Optional[str]
    application_code: Optional[str]
    step: Optional[str]
    match_method: str
    application: dict[str, Any]


class DealumReconciliationError(ValueError):
    """Base error for startup-name reconciliation against Dealum."""


class DealumApplicationNotFoundError(DealumReconciliationError):
    """Raised when no exact Dealum name or application code matches."""


class DealumApplicationAmbiguousError(DealumReconciliationError):
    """Raised when an exact lookup identifies more than one application."""


def dealum_dataset_rel(dataset_slug: str) -> str:
    return f"{dataset_raw_path(canonical_startup_slug(dataset_slug))}/{DEALUM_SUBDIR}"


def dealum_manifest_path(dataset_slug: str) -> str:
    return f"{dealum_dataset_rel(dataset_slug)}/{MANIFEST_JSON}"


def dealum_application_url(
    dealroom_id: Optional[str],
    application_id: Any,
) -> Optional[str]:
    if not dealroom_id or application_id in (None, ""):
        return None
    return DEALUM_APP_URL.format(
        dealroom_id=dealroom_id,
        application_id=application_id,
    )


def reconcile_dealum_startup(
    startup: str,
    *,
    adapter: Optional[DealumAdapter] = None,
) -> DealumMatch:
    requested = startup.strip()
    if not requested:
        raise DealumReconciliationError("Provide a startup name or Dealum application code.")

    adapter = adapter or DealumAdapter()
    if not adapter.is_configured():
        raise ValueError("Dealum is not configured. Set DEALUM_API_KEY and DEALUM_DEALROOM_ID.")

    target_slug = slugify(requested)
    target_code = requested.casefold()
    logger.info(
        "[dealum-reconcile] Starting reconciliation: requested=%r normalized=%r",
        requested,
        target_slug,
    )

    try:
        applications = adapter.list_applications()
    except Exception:
        logger.exception(
            "[dealum-reconcile] Failed to retrieve Dealum applications: requested=%r",
            requested,
        )
        raise

    logger.info(
        "[dealum-reconcile] Retrieved %d Dealum applications for requested=%r",
        len(applications),
        requested,
    )

    name_matches = [
        application
        for application in applications
        if slugify(str(application.get("name") or "")) == target_slug
    ]
    logger.debug(
        "[dealum-reconcile] Normalized-name phase found %d matches: requested=%r normalized=%r",
        len(name_matches),
        requested,
        target_slug,
    )
    if name_matches:
        return _dealum_match(requested, name_matches, "normalized_name", adapter.dealroom_id)

    code_matches = [
        application
        for application in applications
        if str(application.get("code") or "").strip().casefold() == target_code
    ]
    logger.debug(
        "[dealum-reconcile] Application-code phase found %d matches: requested=%r",
        len(code_matches),
        requested,
    )
    if code_matches:
        return _dealum_match(requested, code_matches, "application_code", adapter.dealroom_id)

    logger.warning(
        "[dealum-reconcile] No exact match: requested=%r normalized=%r applications_checked=%d",
        requested,
        target_slug,
        len(applications),
    )
    raise DealumApplicationNotFoundError(
        f"No exact Dealum application match for '{requested}'. "
        "Provide the startup name as shown in Dealum or its application code."
    )


def _dealum_match(
    requested: str,
    applications: list[dict[str, Any]],
    match_method: str,
    dealroom_id: Optional[str],
) -> DealumMatch:
    if len(applications) > 1:
        candidates = [
            {
                "name": application.get("name"),
                "id": application.get("id"),
                "code": application.get("code"),
                "step": application.get("step"),
            }
            for application in applications
        ]
        logger.error(
            "[dealum-reconcile] Ambiguous exact match: requested=%r method=%s candidates=%s",
            requested,
            match_method,
            candidates,
        )
        candidate_names = ", ".join(
            f"{item.get('name') or 'unnamed'} ({item.get('code') or item.get('id') or 'no identifier'})"
            for item in candidates
        )
        raise DealumApplicationAmbiguousError(
            f"Multiple Dealum applications match '{requested}': {candidate_names}."
        )

    application = applications[0]
    matched_name = str(application.get("name") or requested).strip()
    dataset_slug = canonical_startup_slug(matched_name)
    match = DealumMatch(
        requested_startup=requested,
        matched_name=matched_name,
        dataset_slug=dataset_slug,
        dealum_id=application.get("id"),
        dealum_url=dealum_application_url(dealroom_id, application.get("id")),
        application_code=application.get("code"),
        step=application.get("step"),
        match_method=match_method,
        application=application,
    )
    logger.info(
        "[dealum-reconcile] Matched requested=%r to name=%r id=%r code=%r step=%r "
        "method=%s dataset_slug=%r url=%r",
        requested,
        match.matched_name,
        match.dealum_id,
        match.application_code,
        match.step,
        match.match_method,
        match.dataset_slug,
        match.dealum_url,
    )
    return match


def import_startup_from_dealum(
    startup: str,
    *,
    adapter: Optional[DealumAdapter] = None,
    activate: bool = True,
    download_documents: bool = True,
) -> DealumImportResult:
    adapter = adapter or DealumAdapter()
    logger.info("[dealum-import] Starting import: requested=%r", startup)
    match = reconcile_dealum_startup(startup, adapter=adapter)
    application = match.application
    dataset_slug = match.dataset_slug
    logger.info(
        "[dealum-import] Reconciliation complete: requested=%r matched=%r method=%s dataset_slug=%r",
        startup,
        match.matched_name,
        match.match_method,
        dataset_slug,
    )

    storage = get_storage()
    creation_location = dataset_location_for_domain(dataset_slug, "startups")
    active_marker = creation_location.active_marker_rel
    dossier_paths = [
        f"{root}/{subdir}"
        for root in (creation_location.raw_rel, creation_location.parsed_rel)
        for subdir in ("data-room", "linkedin", "dealum", "snippets", "post-deal")
    ]
    dossier_changed = (activate and not storage.exists(active_marker)) or any(
        not storage.exists(path) for path in dossier_paths
    )
    ensure_startup_dossier(dataset_slug, storage=storage, activate=activate)
    dealum_rel = f"{creation_location.raw_rel}/{DEALUM_SUBDIR}"

    previous_manifest = _read_manifest(dataset_slug, dealum_rel=dealum_rel)
    answer_hash = _stable_hash(_application_content_for_hash(application))
    application_changed = answer_hash != previous_manifest.get("application_hash")
    dealum_url_changed = match.dealum_url != previous_manifest.get("dealum_url")

    application_path = f"{dealum_rel}/{APPLICATION_MD}"
    raw_json_path = f"{dealum_rel}/{APPLICATION_RAW_JSON}"
    manifest_path = f"{dealum_rel}/{MANIFEST_JSON}"

    changed = dossier_changed
    if application_changed or dealum_url_changed or not storage.exists(application_path):
        logger.info(
            "[dealum-import] Writing Dealum application: dataset_slug=%r "
            "application_changed=%s dealum_url_changed=%s path=%s",
            dataset_slug,
            application_changed,
            dealum_url_changed,
            application_path,
        )
        storage.write_text(
            application_path,
            render_application_markdown(application, dealum_url=match.dealum_url),
        )
        storage.write_text(raw_json_path, _stable_json(application))
        changed = True

    file_links = adapter.extract_file_links(application)
    previous_files = {
        item.get("url"): item
        for item in previous_manifest.get("files", [])
        if isinstance(item, dict) and item.get("url")
    }
    current_urls = {link.url for link in file_links}
    manifest_files = []
    downloaded_files = 0
    skipped_files = 0

    if download_documents:
        for link in file_links:
            previous = previous_files.get(link.url, {})
            target_rel = f"{dealum_rel}/documents/{link.filename}"
            should_download = not storage.exists(target_rel)
            metadata = {
                "field": link.field,
                "url": link.url,
                "filename": link.filename,
                "path": target_rel,
            }

            if not should_download:
                try:
                    fresh_metadata = adapter.file_metadata(link.url)
                    metadata.update(fresh_metadata)
                    should_download = _file_metadata_changed(previous, metadata)
                except Exception as e:
                    logger.warning(f"[{dataset_slug}] Dealum file metadata check failed for {link.url}: {e}")

            if should_download:
                logger.info(
                    "[dealum-import] Downloading linked file: dataset_slug=%r field=%r target=%s",
                    dataset_slug,
                    link.field,
                    target_rel,
                )
                content, download_metadata = adapter.download_file(link.url)
                storage.write_bytes(target_rel, content)
                metadata.update(download_metadata)
                metadata["content_length"] = metadata.get("content_length") or str(len(content))
                downloaded_files += 1
                changed = True
            else:
                logger.debug(
                    "[dealum-import] Linked file unchanged: dataset_slug=%r target=%s",
                    dataset_slug,
                    target_rel,
                )
                metadata.update({k: v for k, v in previous.items() if k not in metadata or metadata[k] is None})
                skipped_files += 1

            manifest_files.append(metadata)

    stale_files = 0
    for url, previous in previous_files.items():
        if url not in current_urls:
            stale = dict(previous)
            stale["stale"] = True
            manifest_files.append(stale)
            stale_files += 1

    manifest = {
        "source": "dealum",
        "startup": application.get("name") or startup,
        "dataset_slug": dataset_slug,
        "dealum_id": application.get("id"),
        "dealum_url": match.dealum_url,
        "code": application.get("code"),
        "step": application.get("step"),
        "tags": application.get("tags") or [],
        "application_hash": answer_hash,
        "last_sync": int(time.time()),
        "files": manifest_files,
    }

    manifest_changed = _stable_json(manifest_without_last_sync(manifest)) != _stable_json(
        manifest_without_last_sync(previous_manifest)
    )
    if manifest_changed or not storage.exists(manifest_path):
        storage.write_text(manifest_path, _stable_json(manifest))
        changed = True

    logger.info(
        "[dealum-import] Completed import: requested=%r matched=%r dataset_slug=%r changed=%s "
        "downloaded=%d skipped=%d stale=%d step=%r",
        startup,
        match.matched_name,
        dataset_slug,
        changed,
        downloaded_files,
        skipped_files,
        stale_files,
        match.step,
    )
    return DealumImportResult(
        startup=startup,
        dataset_slug=dataset_slug,
        imported=True,
        changed=changed,
        application_found=True,
        dealum_name=match.matched_name,
        dealum_id=match.dealum_id,
        dealum_url=match.dealum_url,
        application_code=match.application_code,
        match_method=match.match_method,
        manifest_path=manifest_path,
        application_path=application_path,
        downloaded_files=downloaded_files,
        skipped_files=skipped_files,
        stale_files=stale_files,
        step=application.get("step"),
    )


def render_application_markdown(
    application: dict[str, Any],
    *,
    dealum_url: Optional[str] = None,
) -> str:
    name = application.get("name") or "Unknown startup"
    lines = [f"# Dealum Application: {name}", ""]
    lines.extend([
        f"- Dealum ID: {application.get('id', '')}",
        f"- Dealum URL: {dealum_url or ''}",
        f"- Code: {application.get('code', '')}",
        f"- Step: {application.get('step', '')}",
        f"- Tags: {', '.join(application.get('tags') or [])}",
        "",
    ])

    contact = application.get("contact") or {}
    if any(contact.get(key) for key in ("firstName", "lastName", "email", "phone")):
        lines.append("## Contact")
        lines.append("")
        full_name = " ".join(part for part in [contact.get("firstName"), contact.get("lastName")] if part)
        if full_name:
            lines.append(f"- Name: {full_name}")
        for key, label in (("email", "Email"), ("phone", "Phone")):
            if contact.get(key):
                lines.append(f"- {label}: {contact[key]}")
        lines.append("")

    answers = application.get("answers") or {}
    if isinstance(answers, dict):
        lines.append("## Application Answers")
        lines.append("")
        for key in sorted(answers.keys()):
            value = answers[key]
            lines.append(f"### {key}")
            lines.append("")
            lines.append(_markdown_value(value))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _markdown_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        rendered = []
        for item in value:
            if isinstance(item, (dict, list)):
                rendered.append(f"- `{json.dumps(item, ensure_ascii=False, sort_keys=True)}`")
            else:
                rendered.append(f"- {item}")
        return "\n".join(rendered)
    if isinstance(value, dict):
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n```"
    return str(value)


def _application_content_for_hash(application: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": application.get("id"),
        "name": application.get("name"),
        "code": application.get("code"),
        "step": application.get("step"),
        "tags": application.get("tags") or [],
        "contact": application.get("contact") or {},
        "answers": application.get("answers") or {},
    }


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _read_manifest(
    dataset_slug: str,
    *,
    dealum_rel: Optional[str] = None,
) -> dict[str, Any]:
    storage = get_storage()
    path = f"{dealum_rel}/{MANIFEST_JSON}" if dealum_rel else dealum_manifest_path(dataset_slug)
    if not storage.exists(path):
        return {}
    try:
        data = json.loads(storage.read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[{dataset_slug}] Could not read Dealum manifest: {e}")
        return {}


def _file_metadata_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous:
        return True
    for key in ("resolved_url", "content_length", "etag"):
        if current.get(key) and previous.get(key) and current.get(key) != previous.get(key):
            return True
    return False


def manifest_without_last_sync(manifest: dict[str, Any]) -> dict[str, Any]:
    clean = dict(manifest or {})
    clean.pop("last_sync", None)
    return clean

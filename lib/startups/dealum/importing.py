from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from lib.adapters.dealum import DealumAdapter
from lib.logger import get_logger
from lib.startups.dealum.manifest import (
    DEALUM_SUBDIR,
    MANIFEST_JSON,
    application_content_for_hash,
    file_metadata_changed,
    manifest_without_last_sync,
    read_manifest,
    stable_hash,
    stable_json,
)
from lib.startups.dealum.matching import reconcile_dealum_startup
from lib.startups.dealum.rendering import render_application_markdown
from lib.startups.dossier import ensure_startup_dossier
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain

logger = get_logger(__name__)

APPLICATION_MD = "application.md"
APPLICATION_RAW_JSON = "application.raw.json"


@dataclass(frozen=True)
class DealumImportResult:
    startup: str
    dataset_slug: str
    imported: bool
    changed: bool
    application_found: bool
    dealum_name: str | None = None
    dealum_id: Any = None
    dealum_url: str | None = None
    application_code: str | None = None
    application_date: str | None = None
    match_method: str | None = None
    selection_method: str | None = None
    manifest_path: str | None = None
    application_path: str | None = None
    downloaded_files: int = 0
    skipped_files: int = 0
    stale_files: int = 0
    step: str | None = None


def import_startup_from_dealum(
    startup: str,
    *,
    adapter: DealumAdapter | None = None,
    activate: bool = True,
    download_documents: bool = True,
) -> DealumImportResult:
    adapter = adapter or DealumAdapter()
    logger.info("[dealum-import] Starting import: requested=%r", startup)
    match = reconcile_dealum_startup(startup, adapter=adapter)
    application = match.application
    dataset_slug = match.dataset_slug

    storage = get_storage()
    location = dataset_location_for_domain(dataset_slug, "startups")
    dossier_paths = [
        f"{root}/{subdir}"
        for root in (location.raw_rel, location.parsed_rel)
        for subdir in (
            "data-room",
            "linkedin",
            "dealum",
            "snippets",
            "post-deal",
        )
    ]
    dossier_changed = (
        activate and not storage.exists(location.active_marker_rel)
    ) or any(not storage.exists(path) for path in dossier_paths)
    ensure_startup_dossier(dataset_slug, storage=storage, activate=activate)
    dealum_rel = f"{location.raw_rel}/{DEALUM_SUBDIR}"

    previous_manifest = read_manifest(
        dataset_slug,
        dealum_rel=dealum_rel,
    )
    answer_hash = stable_hash(application_content_for_hash(application))
    application_changed = (
        answer_hash != previous_manifest.get("application_hash")
    )
    url_changed = match.dealum_url != previous_manifest.get("dealum_url")

    application_path = f"{dealum_rel}/{APPLICATION_MD}"
    raw_json_path = f"{dealum_rel}/{APPLICATION_RAW_JSON}"
    manifest_path = f"{dealum_rel}/{MANIFEST_JSON}"
    changed = dossier_changed
    if (
        application_changed
        or url_changed
        or not storage.exists(application_path)
    ):
        storage.write_text(
            application_path,
            render_application_markdown(
                application,
                dealum_url=match.dealum_url,
            ),
        )
        storage.write_text(raw_json_path, stable_json(application))
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
                    metadata.update(adapter.file_metadata(link.url))
                    should_download = file_metadata_changed(
                        previous,
                        metadata,
                    )
                except Exception as error:
                    logger.warning(
                        "[%s] Dealum file metadata check failed for %s: %s",
                        dataset_slug,
                        link.url,
                        error,
                    )

            if should_download:
                content, download_metadata = adapter.download_file(link.url)
                storage.write_bytes(target_rel, content)
                metadata.update(download_metadata)
                metadata["content_length"] = (
                    metadata.get("content_length") or str(len(content))
                )
                downloaded_files += 1
                changed = True
            else:
                metadata.update(
                    {
                        key: value
                        for key, value in previous.items()
                        if key not in metadata or metadata[key] is None
                    }
                )
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
        "application_date": match.application_date,
        "selection_method": match.selection_method,
        "step": application.get("step"),
        "tags": application.get("tags") or [],
        "application_hash": answer_hash,
        "last_sync": int(time.time()),
        "files": manifest_files,
    }
    manifest_changed = stable_json(
        manifest_without_last_sync(manifest)
    ) != stable_json(manifest_without_last_sync(previous_manifest))
    if manifest_changed or not storage.exists(manifest_path):
        storage.write_text(manifest_path, stable_json(manifest))
        changed = True

    logger.info(
        "[dealum-import] Completed import: requested=%r matched=%r "
        "dataset_slug=%r changed=%s downloaded=%d skipped=%d stale=%d "
        "step=%r",
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
        application_date=match.application_date,
        match_method=match.match_method,
        selection_method=match.selection_method,
        manifest_path=manifest_path,
        application_path=application_path,
        downloaded_files=downloaded_files,
        skipped_files=skipped_files,
        stale_files=stale_files,
        step=application.get("step"),
    )

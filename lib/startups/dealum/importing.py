from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.filesystem import replace_directory_snapshot as _replace_directory_snapshot
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.logging import get_logger
from lib.startups.dealum.manifest import (
    DEALUM_SUBDIR,
    LAST_SUCCESSFUL_PULL_AT,
    MANIFEST_JSON,
    application_content_for_hash,
    read_manifest,
    stable_hash,
    stable_json,
)
from lib.startups.dealum.matching import reconcile_dealum_startup
from lib.startups.dealum.rendering import render_application_markdown
from lib.startups.dossier import ensure_startup_dossier
from lib.startups.dealum.session import current_session
from lib.storage import get_storage
from lib.insights.locking import write_if_changed

logger = get_logger(__name__)

APPLICATION_MD = "application.md"
APPLICATION_RAW_JSON = "application.raw.json"


def _successful_pull_time() -> int:
    return int(time.time())


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
    applications: list[dict[str, Any]] | None = None,
    activate: bool = True,
    download_documents: bool = True,
) -> DealumImportResult:
    adapter = adapter or DealumAdapter()
    logger.info("[dealum-import] Starting import: requested=%r", startup)
    match = reconcile_dealum_startup(
        startup,
        adapter=adapter,
        applications=applications,
    )
    application = match.application
    dataset_slug = match.dataset_slug

    session = current_session()
    if session is not None and dataset_slug in session.source_imports_disabled:
        return DealumImportResult(
            startup=startup, dataset_slug=dataset_slug, imported=False, changed=False,
            application_found=True, step=match.step,
        )
    cache_key = (dataset_slug, download_documents)
    if session is not None and cache_key in session.imports:
        if activate:
            from lib.datasets.state import activate_dataset
            activate_dataset(dataset_slug)
        return session.imports[cache_key]

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
    application_path = f"{dealum_rel}/{APPLICATION_MD}"
    manifest_path = f"{dealum_rel}/{MANIFEST_JSON}"

    staging_rel = (
        f"{location.raw_rel}/.{DEALUM_SUBDIR}-staging-{uuid.uuid4().hex}"
    )
    staging_path = Path(storage.local_path(staging_rel))
    target_path = Path(storage.local_path(dealum_rel))
    storage.mkdir(staging_rel)

    file_links = sorted(
        adapter.extract_file_links(application),
        key=lambda link: (link.field, link.url, link.filename),
    )
    attachment_replacements = {
        link.url: f"dealum-attachment:{link.field}:{link.filename}"
        for link in file_links
    }
    answer_hash = stable_hash(
        application_content_for_hash(
            application,
            attachment_replacements=attachment_replacements,
        )
    )
    manifest_files: list[dict[str, Any]] = []
    downloaded_files = 0

    try:
        storage.write_text(
            f"{staging_rel}/{APPLICATION_MD}",
            render_application_markdown(
                application,
                dealum_url=match.dealum_url,
                attachment_replacements=attachment_replacements,
            ),
        )
        storage.write_text(
            f"{staging_rel}/{APPLICATION_RAW_JSON}",
            stable_json(application),
        )

        if download_documents:
            for link in file_links:
                final_rel = f"{dealum_rel}/documents/{link.filename}"
                staging_file_rel = (
                    f"{staging_rel}/documents/{link.filename}"
                )
                content, download_metadata = adapter.download_file(link.url)
                storage.write_bytes(staging_file_rel, content)
                content_sha256 = hashlib.sha256(content).hexdigest()
                metadata = {
                    "field": link.field,
                    "url": link.url,
                    "filename": link.filename,
                    "path": final_rel,
                    "sha256": content_sha256,
                }
                metadata.update(download_metadata)
                metadata["content_length"] = (
                    metadata.get("content_length") or str(len(content))
                )
                manifest_files.append(metadata)
                downloaded_files += 1

        snapshot_hash = stable_hash(
            {
                "application_hash": answer_hash,
                "files": [
                    {
                        key: item.get(key)
                        for key in (
                            "field",
                            "filename",
                            "sha256",
                        )
                    }
                    for item in manifest_files
                ],
            }
        )
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
            "snapshot_hash": snapshot_hash,
            LAST_SUCCESSFUL_PULL_AT: _successful_pull_time(),
            "files": manifest_files,
        }
        storage.write_text(
            f"{staging_rel}/{MANIFEST_JSON}",
            stable_json(manifest),
        )
        # Reuse identical files rather than rewriting them. The staged hard link
        # keeps both source content and mtime intact if another source changes.
        unchanged_sources = True
        staged_sources = set()
        reusable_sources = []
        for name, _ in storage.list_with_mtime(staging_rel, recursive=True):
            if name in {APPLICATION_RAW_JSON, MANIFEST_JSON}:
                continue
            staged_sources.add(name)
            old, new = f"{dealum_rel}/{name}", f"{staging_rel}/{name}"
            if storage.exists(old) and storage.read_bytes(old) == storage.read_bytes(new):
                reusable_sources.append((old, new))
            else:
                unchanged_sources = False
        previous_sources = {
            name for name, _ in storage.list_with_mtime(dealum_rel, recursive=True)
            if name not in {APPLICATION_RAW_JSON, MANIFEST_JSON}
        }
        if unchanged_sources and staged_sources == previous_sources:
            # No source changes: leave the live snapshot alone. Only refresh
            # bookkeeping when its contents changed; it does not count as activity.
            for filename in (APPLICATION_RAW_JSON, MANIFEST_JSON):
                write_if_changed(storage, f"{dealum_rel}/{filename}",
                                 storage.read_text(f"{staging_rel}/{filename}"))
        else:
            for old, new in reusable_sources:
                Path(storage.local_path(new)).unlink()
                os.link(storage.local_path(old), storage.local_path(new))
            _replace_directory_snapshot(staging_path, target_path)
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)

    previous_paths = {
        item.get("path")
        for item in previous_manifest.get("files", [])
        if isinstance(item, dict) and item.get("path")
    }
    current_paths = {
        item.get("path")
        for item in manifest_files
        if item.get("path")
    }
    stale_files = len(previous_paths - current_paths)
    changed = (
        dossier_changed
        or previous_manifest.get("snapshot_hash") != snapshot_hash
    )

    logger.info(
        "[dealum-import] Completed import: requested=%r matched=%r "
        "dataset_slug=%r changed=%s downloaded=%d removed=%d step=%r",
        startup,
        match.matched_name,
        dataset_slug,
        changed,
        downloaded_files,
        stale_files,
        match.step,
    )
    result = DealumImportResult(
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
        skipped_files=0,
        stale_files=stale_files,
        step=application.get("step"),
    )
    if session is not None:
        session.imports[cache_key] = result
    return result

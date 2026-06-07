from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from lib.active_dataset import activate_dataset
from lib.adapters.dealum import DealumAdapter, DealumFileLink
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from lib.storage_domains import dataset_raw_path

logger = get_logger(__name__)

DEALUM_SUBDIR = "dealum"
APPLICATION_MD = "application.md"
APPLICATION_RAW_JSON = "application.raw.json"
MANIFEST_JSON = "manifest.json"


@dataclass(frozen=True)
class DealumImportResult:
    startup: str
    dataset_slug: str
    imported: bool
    changed: bool
    application_found: bool
    manifest_path: Optional[str] = None
    application_path: Optional[str] = None
    downloaded_files: int = 0
    skipped_files: int = 0
    stale_files: int = 0
    step: Optional[str] = None


def dealum_dataset_rel(dataset_slug: str) -> str:
    return f"{dataset_raw_path(dataset_slug)}/{DEALUM_SUBDIR}"


def dealum_manifest_path(dataset_slug: str) -> str:
    return f"{dealum_dataset_rel(dataset_slug)}/{MANIFEST_JSON}"


def import_startup_from_dealum(
    startup: str,
    *,
    adapter: Optional[DealumAdapter] = None,
    activate: bool = True,
    download_documents: bool = True,
) -> DealumImportResult:
    adapter = adapter or DealumAdapter()
    if not adapter.is_configured():
        raise ValueError("Dealum is not configured. Set DEALUM_API_KEY and DEALUM_DEALROOM_ID.")

    application = adapter.find_application(startup)
    dataset_slug = slugify(application.get("name", startup) if application else startup)
    if not application:
        return DealumImportResult(
            startup=startup,
            dataset_slug=dataset_slug,
            imported=False,
            changed=False,
            application_found=False,
        )

    storage = get_storage()
    raw_rel = dataset_raw_path(dataset_slug)
    dealum_rel = dealum_dataset_rel(dataset_slug)
    storage.mkdir(dealum_rel)

    previous_manifest = _read_manifest(dataset_slug)
    answer_hash = _stable_hash(_application_content_for_hash(application))
    application_changed = answer_hash != previous_manifest.get("application_hash")

    application_path = f"{dealum_rel}/{APPLICATION_MD}"
    raw_json_path = f"{dealum_rel}/{APPLICATION_RAW_JSON}"
    manifest_path = dealum_manifest_path(dataset_slug)

    changed = False
    if application_changed or not storage.exists(application_path):
        storage.write_text(application_path, render_application_markdown(application))
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
            target_rel = _document_rel(dataset_slug, link)
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
                content, download_metadata = adapter.download_file(link.url)
                storage.write_bytes(target_rel, content)
                metadata.update(download_metadata)
                metadata["content_length"] = metadata.get("content_length") or str(len(content))
                downloaded_files += 1
                changed = True
            else:
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

    if activate and not storage.exists(f"{raw_rel}/__active_dataset__"):
        activate_dataset(dataset_slug)
        changed = True

    return DealumImportResult(
        startup=startup,
        dataset_slug=dataset_slug,
        imported=True,
        changed=changed,
        application_found=True,
        manifest_path=manifest_path,
        application_path=application_path,
        downloaded_files=downloaded_files,
        skipped_files=skipped_files,
        stale_files=stale_files,
        step=application.get("step"),
    )


def render_application_markdown(application: dict[str, Any]) -> str:
    name = application.get("name") or "Unknown startup"
    lines = [f"# Dealum Application: {name}", ""]
    lines.extend([
        f"- Dealum ID: {application.get('id', '')}",
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


def _read_manifest(dataset_slug: str) -> dict[str, Any]:
    storage = get_storage()
    path = dealum_manifest_path(dataset_slug)
    if not storage.exists(path):
        return {}
    try:
        data = json.loads(storage.read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[{dataset_slug}] Could not read Dealum manifest: {e}")
        return {}


def _document_rel(dataset_slug: str, link: DealumFileLink) -> str:
    return f"{dealum_dataset_rel(dataset_slug)}/documents/{link.filename}"


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

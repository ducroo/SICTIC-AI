from __future__ import annotations

import hashlib
import json
from typing import Any

from lib.logger import get_logger
from lib.startups.identity import canonical_startup_slug
from lib.storage import get_storage
from lib.datasets.paths import dataset_raw_path

logger = get_logger(__name__)

DEALUM_SUBDIR = "dealum"
MANIFEST_JSON = "manifest.json"
LAST_SUCCESSFUL_PULL_AT = "last_successful_pull_at"


def dealum_dataset_rel(dataset_slug: str) -> str:
    slug = canonical_startup_slug(dataset_slug)
    return f"{dataset_raw_path(slug)}/{DEALUM_SUBDIR}"


def dealum_manifest_path(dataset_slug: str) -> str:
    return f"{dealum_dataset_rel(dataset_slug)}/{MANIFEST_JSON}"


def read_manifest(
    dataset_slug: str,
    *,
    dealum_rel: str | None = None,
) -> dict[str, Any]:
    storage = get_storage()
    path = (
        f"{dealum_rel}/{MANIFEST_JSON}"
        if dealum_rel
        else dealum_manifest_path(dataset_slug)
    )
    if not storage.exists(path):
        return {}
    try:
        data = json.loads(storage.read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception as error:
        logger.warning(
            "[%s] Could not read Dealum manifest: %s",
            dataset_slug,
            error,
        )
        return {}


def dealum_url_for_startup(dataset_slug: str) -> str | None:
    """Return the stored Dealum application URL for a startup, if any."""
    url = read_manifest(dataset_slug).get("dealum_url")
    if not isinstance(url, str) or not url.strip():
        return None
    return url.strip()


def application_content_for_hash(
    application: dict[str, Any],
    *,
    attachment_replacements: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": application.get("id"),
        "name": application.get("name"),
        "code": application.get("code"),
        "tags": sorted(str(tag) for tag in application.get("tags") or []),
        "contact": application.get("contact") or {},
        "answers": replace_attachment_urls(
            application.get("answers") or {},
            attachment_replacements or {},
        ),
    }


def replace_attachment_urls(
    value: Any,
    replacements: dict[str, str],
) -> Any:
    """Replace volatile Dealum attachment URLs with stable identities."""
    if isinstance(value, str):
        normalized = value
        for url, identity in replacements.items():
            normalized = normalized.replace(url, identity)
        return normalized
    if isinstance(value, list):
        return [
            replace_attachment_urls(item, replacements)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: replace_attachment_urls(item, replacements)
            for key, item in value.items()
        }
    return value


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def manifest_without_last_sync(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    clean = dict(manifest or {})
    clean.pop("last_sync", None)
    return clean

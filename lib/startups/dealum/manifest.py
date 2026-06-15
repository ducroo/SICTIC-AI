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


def file_metadata_changed(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    if not previous:
        return True
    return any(
        current.get(key)
        and previous.get(key)
        and current.get(key) != previous.get(key)
        for key in ("resolved_url", "content_length", "etag")
    )


def application_content_for_hash(
    application: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": application.get("id"),
        "name": application.get("name"),
        "code": application.get("code"),
        "step": application.get("step"),
        "tags": application.get("tags") or [],
        "contact": application.get("contact") or {},
        "answers": application.get("answers") or {},
    }


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

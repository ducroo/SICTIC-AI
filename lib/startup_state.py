from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from lib.dealum_import import dealum_manifest_path
from lib.slugify import slugify
from lib.storage import get_storage
from lib.storage_domains import find_dataset_location


@dataclass(frozen=True)
class StartupState:
    dataset_slug: str
    dataset_exists: bool
    source: Optional[str] = None
    dealum_id: Optional[int] = None
    step: Optional[str] = None
    tags: tuple[str, ...] = ()
    last_sync: Optional[int] = None
    has_pitch_deck: bool = False
    has_financials: bool = False

    def allows(self, action: str) -> bool:
        action_slug = action.replace("-", "_").lower()
        step = (self.step or "").strip().lower()
        if action_slug in {"startup_profile", "profile"}:
            return self.dataset_exists
        if action_slug in {"jury", "jury_review"}:
            return step == "jury"
        if action_slug in {"dd_checks", "due_diligence"}:
            return self.dataset_exists and (self.has_pitch_deck or step in {"jury", "due diligence", "dd"})
        return self.dataset_exists


def get_startup_state(startup: str) -> StartupState:
    dataset_slug = slugify(startup)
    storage = get_storage()
    location = find_dataset_location(dataset_slug)
    dataset_exists = location is not None
    manifest = _read_dealum_manifest(dataset_slug) if dataset_exists else {}
    files = manifest.get("files", []) if isinstance(manifest.get("files"), list) else []

    has_pitch_deck = any(
        "pitch" in str(item.get("field", "")).lower()
        or "pitch" in str(item.get("filename", "")).lower()
        for item in files
        if isinstance(item, dict) and not item.get("stale")
    )
    has_financials = any(
        "financial" in str(item.get("field", "")).lower()
        or str(item.get("filename", "")).lower().endswith((".xls", ".xlsx"))
        for item in files
        if isinstance(item, dict) and not item.get("stale")
    )

    return StartupState(
        dataset_slug=dataset_slug,
        dataset_exists=dataset_exists,
        source=manifest.get("source"),
        dealum_id=manifest.get("dealum_id"),
        step=manifest.get("step"),
        tags=tuple(manifest.get("tags") or ()),
        last_sync=manifest.get("last_sync"),
        has_pitch_deck=has_pitch_deck,
        has_financials=has_financials,
    )


def _read_dealum_manifest(dataset_slug: str) -> dict[str, Any]:
    storage = get_storage()
    path = dealum_manifest_path(dataset_slug)
    if not storage.exists(path):
        return {}
    try:
        parsed = json.loads(storage.read_text(path))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

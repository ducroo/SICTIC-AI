"""Persistent list of LinkedIn profiles that still require resolution."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from lib.infrastructure.configuration import get_env_var
from lib.linkedin_ids import normalize_linkedin_id

_PROCESS_LOCK = threading.Lock()

STATUS_OPEN = "open"
STATUS_FAILED = "failed"
STATUS_NOT_FOUND = "not_found"
TERMINAL_STATUSES = frozenset({STATUS_FAILED, STATUS_NOT_FOUND})
KNOWN_STATUSES = frozenset({STATUS_OPEN, *TERMINAL_STATUSES})
_LEGACY_STATUSES = {
    "PENDING": STATUS_OPEN,
    "SCRAPE_FAILED": STATUS_FAILED,
    "URL_NOT_FOUND": STATUS_FAILED,
    "DO_NOT_SCRAPE": STATUS_NOT_FOUND,
}


def default_registry_path() -> Path:
    return Path(get_env_var("REPO_PATH")) / "cache" / "linkedin_missing_profiles.json"


class LinkedInRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_registry_path()

    @staticmethod
    def _normalize_entry(entry: dict) -> dict:
        normalized = dict(entry)
        datasets = normalized.get("datasets")
        if not datasets and normalized.get("dataset"):
            datasets = [normalized["dataset"]]
        normalized["datasets"] = sorted(set(datasets or []))
        normalized.pop("dataset", None)
        status = str(normalized.get("status") or STATUS_OPEN)
        normalized["status"] = _LEGACY_STATUSES.get(status, status)
        normalized["linkedin_id"] = normalize_linkedin_id(
            normalized.get("linkedin_id", "")
        )
        return normalized

    @classmethod
    def _canonicalize(cls, entries: dict[str, dict]) -> dict[str, dict]:
        canonical: dict[str, dict] = {}
        for source_key, value in entries.items():
            if not isinstance(value, dict):
                continue
            entry = cls._normalize_entry(value)
            key = entry.get("linkedin_id") or source_key
            existing = canonical.get(key, {})
            canonical[key] = {
                **existing,
                **entry,
                "datasets": sorted(
                    set(existing.get("datasets", []))
                    | set(entry.get("datasets", []))
                ),
                "full_name": entry.get("full_name")
                or existing.get("full_name", ""),
            }
        return canonical

    def load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as error:
            raise RuntimeError(
                f"Failed to read LinkedIn registry {self.path}: {error}"
            ) from error
        if not isinstance(data, dict):
            raise ValueError(f"LinkedIn registry must contain an object: {self.path}")
        return self._canonicalize(data)

    def save(self, entries: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self._canonicalize(entries), indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        with lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass

    def update(self, mutator) -> dict[str, dict]:
        with _PROCESS_LOCK:
            with self._locked():
                entries = self.load()
                mutator(entries)
                self.save(entries)
                return entries

    @staticmethod
    def _find_in_entries(
        entries: dict[str, dict],
        key: str,
        linkedin_id: str = "",
        full_name: str = "",
    ) -> tuple[str, dict] | None:
        if key in entries:
            return key, entries[key]
        normalized_key = normalize_linkedin_id(key)
        normalized_linkedin_id = normalize_linkedin_id(linkedin_id)
        for entry_key, entry in entries.items():
            if normalized_key and normalize_linkedin_id(entry_key) == normalized_key:
                return entry_key, entry
            if normalized_linkedin_id and normalize_linkedin_id(
                entry.get("linkedin_id", "")
            ) == normalized_linkedin_id:
                return entry_key, entry
            if full_name and entry.get("full_name", "").strip().casefold() == (
                full_name.strip().casefold()
            ):
                return entry_key, entry
        return None

    def find(
        self,
        key: str,
        linkedin_id: str = "",
        full_name: str = "",
    ) -> tuple[str, dict] | None:
        return self._find_in_entries(self.load(), key, linkedin_id, full_name)

    def upsert(
        self,
        key: str,
        *,
        dataset: str,
        full_name: str,
        linkedin_id: str,
        status: str,
    ) -> None:
        canonical_id = normalize_linkedin_id(linkedin_id)
        if not canonical_id:
            raise ValueError("Open LinkedIn profiles require a LinkedIn ID")

        def mutate(entries):
            registered = self._find_in_entries(
                entries, key, canonical_id, full_name
            )
            existing_key, existing = registered or (canonical_id, {})
            if existing_key != canonical_id:
                entries.pop(existing_key, None)
            existing = self._normalize_entry(existing)
            datasets = set(existing.get("datasets", []))
            datasets.add(dataset)
            entries[canonical_id] = {
                **existing,
                "datasets": sorted(datasets),
                "full_name": full_name or existing.get("full_name", ""),
                "linkedin_id": canonical_id,
                "status": status,
            }

        self.update(mutate)

    def set_status(self, linkedin_ids: list[str], status: str) -> None:
        normalized_ids = {
            normalize_linkedin_id(linkedin_id)
            for linkedin_id in linkedin_ids
            if normalize_linkedin_id(linkedin_id)
        }

        def mutate(entries):
            for entry in entries.values():
                if entry.get("linkedin_id") in normalized_ids:
                    entry["status"] = status

        self.update(mutate)

    def remove_identity(self, linkedin_id: str) -> None:
        normalized_id = normalize_linkedin_id(linkedin_id)

        def mutate(entries):
            for key in list(entries):
                if normalize_linkedin_id(key) == normalized_id or normalize_linkedin_id(
                    entries[key].get("linkedin_id", "")
                ) == normalized_id:
                    del entries[key]

        self.update(mutate)

    def mark_status(self, linkedin_id: str, status: str) -> bool:
        changed = False
        normalized_id = normalize_linkedin_id(linkedin_id)

        def mutate(entries):
            nonlocal changed
            for key, entry in entries.items():
                if normalize_linkedin_id(key) == normalized_id or normalize_linkedin_id(
                    entry.get("linkedin_id", "")
                ) == normalized_id:
                    entry["status"] = status
                    changed = True

        self.update(mutate)
        return changed

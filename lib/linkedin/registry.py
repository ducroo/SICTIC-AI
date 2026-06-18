from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from lib.env import get_env_var
from lib.linkedin_ids import normalize_linkedin_id
from lib.logger import get_logger

logger = get_logger(__name__)
_PROCESS_LOCK = threading.Lock()


def default_registry_path() -> Path:
    return (
        Path(get_env_var("REPO_PATH"))
        / "cache"
        / "linkedin_missing_profiles.json"
    )


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
        return normalized

    def load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read LinkedIn registry {self.path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(f"LinkedIn registry must contain an object: {self.path}")
        return {
            key: self._normalize_entry(value)
            for key, value in data.items()
            if isinstance(value, dict)
        }

    def save(self, entries: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            key: self._normalize_entry(value)
            for key, value in entries.items()
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(normalized, indent=2),
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

    def entries_for_dataset(self, dataset: str) -> dict[str, dict]:
        return {
            key: value
            for key, value in self.load().items()
            if dataset in value.get("datasets", [])
        }

    def find(
        self,
        key: str,
        linkedin_id: str = "",
        full_name: str = "",
    ) -> tuple[str, dict] | None:
        entries = self.load()
        if key in entries:
            return key, entries[key]
        normalized_key = normalize_linkedin_id(key)
        normalized_linkedin_id = normalize_linkedin_id(linkedin_id)
        for entry_key, entry in entries.items():
            if normalized_key and normalize_linkedin_id(entry_key) == normalized_key:
                return entry_key, entry
            if (
                normalized_linkedin_id
                and normalize_linkedin_id(entry.get("linkedin_id", ""))
                == normalized_linkedin_id
            ):
                return entry_key, entry
            if (
                full_name
                and entry.get("full_name", "").strip().casefold()
                == full_name.strip().casefold()
            ):
                return entry_key, entry
        return None

    def upsert(
        self,
        key: str,
        *,
        dataset: str,
        full_name: str,
        linkedin_id: str,
        status: str,
    ) -> None:
        def mutate(entries):
            existing = self._normalize_entry(entries.get(key, {}))
            datasets = set(existing.get("datasets", []))
            datasets.add(dataset)
            entries[key] = {
                **existing,
                "datasets": sorted(datasets),
                "full_name": full_name or existing.get("full_name", ""),
                "linkedin_id": linkedin_id or existing.get("linkedin_id", ""),
                "status": status,
            }

        self.update(mutate)

    def remove_identity(self, linkedin_id: str) -> None:
        normalized_linkedin_id = normalize_linkedin_id(linkedin_id)

        def mutate(entries):
            for key in list(entries):
                if (
                    normalize_linkedin_id(key) == normalized_linkedin_id
                    or normalize_linkedin_id(entries[key].get("linkedin_id", ""))
                    == normalized_linkedin_id
                ):
                    del entries[key]

        self.update(mutate)

    def mark_status(self, linkedin_id: str, status: str) -> bool:
        changed = False
        normalized_linkedin_id = normalize_linkedin_id(linkedin_id)

        def mutate(entries):
            nonlocal changed
            for key, entry in entries.items():
                if (
                    normalize_linkedin_id(key) == normalized_linkedin_id
                    or normalize_linkedin_id(entry.get("linkedin_id", ""))
                    == normalized_linkedin_id
                ):
                    entry["status"] = status
                    changed = True

        self.update(mutate)
        return changed

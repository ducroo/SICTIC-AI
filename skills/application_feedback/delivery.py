"""Durable delivery receipts, independent of insight generation and freshness."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from lib.infrastructure.ai_text_generation.json import validate_json_schema
from lib.infrastructure.configuration import load_repository_config
from lib.insights.locking import manifest_write_lock, write_if_changed
from lib.storage import get_storage


@contextmanager
def delivery_journal(path: str):
    """Serialize delivery decisions and fail closed on unreadable receipt state.

    Hold the shared file lock through the send and its acknowledgement. A crash
    after recording an attempt leaves it uncertain rather than silently retryable.
    """
    storage = get_storage()
    with manifest_write_lock(Path(storage.local_path(path))):
        entries = json.loads(storage.read_text(path)) if storage.exists(path) else {}
        schema = load_repository_config("application_feedback", "delivery_schema")
        validate_json_schema(entries, schema)

        def save():
            validate_json_schema(entries, schema)
            write_if_changed(storage, path, json.dumps(entries, indent=2) + "\n")

        yield entries, save

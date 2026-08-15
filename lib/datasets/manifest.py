"""Persistent checkpoints for dataset conversion and indexing."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.logger import get_logger

logger = get_logger(__name__)

MANIFEST_FILENAME = ".ingestion-manifest.json"
MANIFEST_VERSION = 1
PARSER_VERSION = "docling-page-markers-v1"
CHUNKER_VERSION = "markdown-1000-100-v1"


def content_hash(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def ignored_parse_is_current(
    state: dict[str, Any] | None,
    *,
    source_sha256: str,
) -> bool:
    """Return whether an intentionally empty parse still matches its source."""
    return bool(
        state
        and state.get("source_sha256") == source_sha256
        and state.get("parser_version") == PARSER_VERSION
        and state.get("ignored_reason")
    )


@dataclass
class IngestionManifest:
    storage: Any
    parsed_rel: str
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    indexed_dataset_revision: str = ""

    @property
    def path(self) -> str:
        return f"{self.parsed_rel}/{MANIFEST_FILENAME}"

    @classmethod
    def load(cls, storage, parsed_rel: str) -> "IngestionManifest":
        manifest = cls(storage=storage, parsed_rel=parsed_rel)
        path = manifest.path
        if not storage.exists(path):
            return manifest
        try:
            data = json.loads(storage.read_text(path))
            if data.get("version") != MANIFEST_VERSION:
                logger.warning(
                    "Ignoring unsupported ingestion manifest version in %s.",
                    path,
                )
                return manifest
            documents = data.get("documents", {})
            if not isinstance(documents, dict):
                raise ValueError("'documents' must be an object")
            manifest.documents = documents
            revision = data.get("indexed_dataset_revision", "")
            if not isinstance(revision, str):
                raise ValueError("'indexed_dataset_revision' must be a string")
            manifest.indexed_dataset_revision = revision
        except Exception as exc:
            logger.warning("Ignoring invalid ingestion manifest %s: %s", path, exc)
        return manifest

    def save(self) -> None:
        payload = {
            "version": MANIFEST_VERSION,
            "indexed_dataset_revision": self.indexed_dataset_revision,
            "documents": self.documents,
        }
        target = Path(self.storage.local_path(self.path))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)

    def state(self, filename: str) -> dict[str, Any]:
        return self.documents.setdefault(filename, {})

    def remove(self, filename: str) -> None:
        self.documents.pop(filename, None)

    def update_indexed_dataset_revision(self) -> str:
        indexed_documents = []
        for filename, state in sorted(self.documents.items()):
            parsed_sha = state.get("indexed_parsed_sha256")
            chunker_version = state.get("indexed_chunker_version")
            embedding_model = state.get("indexed_embedding_model")
            if not all((parsed_sha, chunker_version, embedding_model)):
                continue
            document = {
                "filename": filename,
                "parsed_sha256": parsed_sha,
                "chunker_version": chunker_version,
                "embedding_model": embedding_model,
            }
            # Only recorded once sparse vectors exist, so datasets that have
            # not been rebuilt for hybrid search keep their current revision
            # and their reusable insights.
            sparse_version = state.get("indexed_sparse_version")
            if sparse_version:
                document["sparse_version"] = sparse_version
            indexed_documents.append(document)

        self.indexed_dataset_revision = content_hash(
            json.dumps(
                indexed_documents,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return self.indexed_dataset_revision

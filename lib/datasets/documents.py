"""Resolve proposed source-document paths against parsed dataset documents."""

from __future__ import annotations

from pathlib import PurePosixPath

from rapidfuzz import fuzz

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_parsed_path
from lib.datasets.source import parsed_filepath
from lib.storage import get_storage


def _normalized_path(value: str) -> str:
    return "/".join(
        part
        for part in value.strip().strip("'\"").replace("\\", "/").split("/")
        if part not in {"", "."}
    ).casefold()


def _path_aliases(value: str) -> set[str]:
    normalized = _normalized_path(value)
    if not normalized:
        return set()
    aliases = {normalized, PurePosixPath(normalized).name}
    if normalized.endswith(".md"):
        without_markdown = normalized[:-3]
        aliases.update(
            {
                without_markdown,
                PurePosixPath(without_markdown).name,
            }
        )
    return aliases


def _document_paths(dataset_name: str) -> list[str]:
    parsed_root = dataset_parsed_path(dataset_name)
    storage = get_storage()
    manifest = IngestionManifest.load(storage, parsed_root)
    paths = {
        source_path
        for source_path in manifest.documents
        if storage.exists(parsed_filepath(parsed_root, source_path))
    }
    known_parsed_paths = {
        parsed_filepath(parsed_root, source_path).removeprefix(
            f"{parsed_root}/"
        )
        for source_path in paths
    }
    paths.update(
        relative_path
        for relative_path, _mtime in storage.list_with_mtime(
            parsed_root,
            recursive=True,
        )
        if relative_path.lower().endswith(".md")
        and relative_path not in known_parsed_paths
    )
    if not paths:
        raise ValueError(
            f"Dataset '{dataset_name}' has no parsed Markdown documents."
        )
    return sorted(paths)


def resolve_document_path(
    dataset_name: str,
    proposed_path: str,
) -> tuple[str, float]:
    """Return the closest source-document path and its 0-100 match score."""
    proposed_aliases = _path_aliases(proposed_path)
    if not proposed_aliases:
        raise ValueError("A proposed document path is required.")

    scored_paths = []
    for document_path in _document_paths(dataset_name):
        document_aliases = _path_aliases(document_path)
        score = max(
            fuzz.ratio(proposed, candidate)
            for proposed in proposed_aliases
            for candidate in document_aliases
        )
        scored_paths.append((score, document_path))

    score, matched_path = max(
        scored_paths,
        key=lambda item: (item[0], item[1]),
    )
    return matched_path, float(score)


__all__ = ["resolve_document_path"]

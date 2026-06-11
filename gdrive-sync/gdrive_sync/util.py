from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path, PurePosixPath


def clean_rel(path: str | os.PathLike | None) -> str:
    if path is None:
        return ""
    rel = str(path).replace("\\", "/").strip("/")
    if rel in {"", "."}:
        return ""
    if rel.startswith("/"):
        raise ValueError(f"paths must be relative to the sync root: {path!r}")
    parts = PurePosixPath(rel).parts
    if ".." in parts:
        raise ValueError(f"paths must not contain '..': {path!r}")
    return rel


def is_hidden_rel(rel: str) -> bool:
    return any(part.startswith(".") for part in PurePosixPath(rel).parts)


def is_excluded(rel: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    rel = clean_rel(rel)
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern):
            return True
        if pattern.endswith("/**") and rel == pattern[:-3].rstrip("/"):
            return True
    return False


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def conflict_name(path: str, tag: str, existing: set[str]) -> str:
    rel = PurePosixPath(path)
    suffix = "".join(rel.suffixes)
    stem = rel.name[: -len(suffix)] if suffix else rel.name
    parent = "" if str(rel.parent) == "." else str(rel.parent)
    index = 1
    while True:
        marker = tag if index == 1 else f"{tag}-{index}"
        name = f"{stem}.{marker}{suffix}"
        candidate = f"{parent}/{name}" if parent else name
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        index += 1

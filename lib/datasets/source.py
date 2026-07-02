"""Discovery and hashing of ingestible dataset source files."""

from __future__ import annotations

from dataclasses import dataclass

from lib.datasets.manifest import content_hash

IGNORED_EXTENSIONS = (
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wmv",
    ".mp3",
    ".wav",
    ".aac",
    ".flac",
    ".m4a",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".exe",
    ".bin",
    ".dll",
    ".so",
    ".dmg",
    ".gdoc",
    ".gsheet",
    ".gslide",
    ".gdraw",
)
IGNORED_FILENAMES = {
    ".ds_store",
    "__active_dataset__.md",
    "__archived_dataset__.md",
    "application.raw.json",
    "manifest.json",
}


@dataclass(frozen=True)
class SourceDocument:
    filename: str
    mtime: float
    sha256: str


def list_source_files(storage, raw_rel: str) -> list[tuple[str, float]]:
    """Return relative filenames and mtimes for ingestible source files."""
    return [
        (name, mtime)
        for name, mtime in storage.list_with_mtime(raw_rel, recursive=True)
        if name.rsplit("/", 1)[-1].lower() not in IGNORED_FILENAMES
        and not name.lower().endswith(IGNORED_EXTENSIONS)
    ]


def snapshot_source_files(storage, raw_rel: str) -> list[SourceDocument]:
    """Hash the current source inventory."""
    return [
        SourceDocument(
            filename=filename,
            mtime=mtime,
            sha256=content_hash(storage.read_bytes(f"{raw_rel}/{filename}")),
        )
        for filename, mtime in list_source_files(storage, raw_rel)
    ]


def parsed_filepath(parsed_rel: str, filename: str) -> str:
    if filename.lower().endswith(".md"):
        return f"{parsed_rel}/{filename}"
    return f"{parsed_rel}/{filename}.md"

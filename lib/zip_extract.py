"""Safe ZIP extraction for uploaded data-room archives."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Archives and executables stay out of the dossier; ingestion already ignores them.
_SKIP_SUFFIXES = {
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".tgz",
    ".exe",
    ".dll",
    ".so",
    ".bin",
    ".dmg",
}


@dataclass(frozen=True)
class ExtractedDataroom:
    """Files written under ``destination`` with paths relative to that root."""

    files: tuple[str, ...]
    skipped: tuple[str, ...]
    total_bytes: int


def _safe_member_path(name: str) -> PurePosixPath | None:
    """Return a relative POSIX path, or None when the member must be skipped."""
    raw = name.replace("\\", "/").strip()
    if not raw or raw.endswith("/"):
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe path inside ZIP: {name!r}")
    # Drop a single top-level folder when every member shares it (handled by caller).
    if not path.name or path.name.startswith("."):
        return None
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return None
    return path


def extract_dataroom_zip(
    payload: bytes,
    destination: Path,
    *,
    max_members: int = 400,
    max_uncompressed_bytes: int = 400 * 1024 * 1024,
) -> ExtractedDataroom:
    """Extract ingestible members into ``destination``.

    Rejects path traversal, caps member count and uncompressed size, and skips
    nested archives. Returns relative POSIX paths of written files.
    """
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not payload:
        raise ValueError("The ZIP file is empty.")

    written: list[str] = []
    skipped: list[str] = []
    total = 0

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as error:
        raise ValueError("Upload a valid ZIP archive.") from error

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise ValueError("The ZIP archive has no files.")

        # Strip a shared top-level folder so nested datarooms land flat under dest.
        prefixes = set()
        for info in infos:
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if parts:
                prefixes.add(parts[0])
        strip_root = next(iter(prefixes)) if len(prefixes) == 1 else None

        for info in infos:
            if info.file_size < 0:
                raise ValueError("The ZIP archive is invalid.")
            try:
                member = _safe_member_path(info.filename)
            except ValueError:
                raise
            if member is None:
                skipped.append(info.filename)
                continue
            if strip_root and member.parts and member.parts[0] == strip_root:
                member = PurePosixPath(*member.parts[1:]) if len(member.parts) > 1 else None
                if member is None or not member.name:
                    skipped.append(info.filename)
                    continue
            if len(written) >= max_members:
                raise ValueError(
                    f"The ZIP has more than {max_members} documents. "
                    "Upload a smaller data room."
                )
            total += info.file_size
            if total > max_uncompressed_bytes:
                raise ValueError(
                    "The extracted data room is larger than 400 MB. "
                    "Upload a smaller archive."
                )
            target = (destination / Path(*member.parts)).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"Unsafe path inside ZIP: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as out:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            written.append(member.as_posix())

    if not written:
        raise ValueError(
            "No reviewable documents were found in the ZIP. "
            "Include PDFs, Office files, or text documents."
        )
    return ExtractedDataroom(
        files=tuple(written),
        skipped=tuple(skipped),
        total_bytes=total,
    )

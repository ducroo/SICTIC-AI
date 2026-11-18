import io
import zipfile
from pathlib import Path

import pytest

from lib.zip_extract import extract_dataroom_zip


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_extract_dataroom_zip_writes_files_and_strips_root(tmp_path: Path):
    payload = _zip_bytes(
        {
            "Room/1_Business/pitch.pdf": b"%PDF-1.4",
            "Room/2_Company/articles.docx": b"PK",
            "Room/nested.zip": b"nested",
        }
    )

    result = extract_dataroom_zip(payload, tmp_path / "out")

    assert "1_Business/pitch.pdf" in result.files
    assert "2_Company/articles.docx" in result.files
    assert any(name.endswith("nested.zip") for name in result.skipped)
    assert (tmp_path / "out" / "1_Business" / "pitch.pdf").read_bytes() == b"%PDF-1.4"


def test_extract_dataroom_zip_rejects_path_traversal(tmp_path: Path):
    payload = _zip_bytes({"../escape.pdf": b"%PDF"})

    with pytest.raises(ValueError, match="Unsafe path"):
        extract_dataroom_zip(payload, tmp_path / "out")


def test_extract_dataroom_zip_rejects_empty_archive(tmp_path: Path):
    with pytest.raises(ValueError, match="no files"):
        extract_dataroom_zip(_zip_bytes({}), tmp_path / "out")

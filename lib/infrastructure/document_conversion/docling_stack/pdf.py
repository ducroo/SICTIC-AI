from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager


def repair_pdf(filepath: str) -> str:
    """Normalize a malformed PDF and return its temporary path."""
    ghostscript = shutil.which("gs")
    if not ghostscript:
        raise RuntimeError("Ghostscript executable 'gs' not found.")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
        repaired_path = temporary.name
    try:
        subprocess.run(
            [
                ghostscript,
                "-q",
                "-dNOPAUSE",
                "-dBATCH",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-sOutputFile={repaired_path}",
                filepath,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return repaired_path
    except Exception:
        try:
            os.remove(repaired_path)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def repaired_pdf(filepath: str) -> Iterator[str]:
    """Yield a Ghostscript-normalized temporary PDF path."""
    repaired_path = repair_pdf(filepath)
    try:
        yield repaired_path
    finally:
        try:
            os.remove(repaired_path)
        except FileNotFoundError:
            pass


def convert_repaired_pdf(
    filepath: str,
    convert: Callable[[str], str],
) -> str:
    """Normalize a malformed PDF with Ghostscript, then convert it."""
    with repaired_pdf(filepath) as repaired_path:
        return convert(repaired_path)

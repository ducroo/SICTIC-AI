from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager

from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# At Docling OCR's 3x scale this bounds the longest bitmap edge to 4320 px.
# Resize vector page coordinates, not a raster image, to retain text and detail.
_MAX_PAGE_POINTS = 1440


@contextmanager
def bounded_pdf(filepath: str) -> Iterator[str]:
    """Use a temporary, proportionally scaled copy only for oversized PDF pages."""
    import pypdfium2 as pdfium
    from docling.utils.locks import pypdfium2_lock

    temporary_path = None
    try:
        # PDFium is not thread safe. Share Docling's lock for native PDF access,
        # but release it before conversion (which acquires the same lock).
        with pypdfium2_lock:
            try:
                document = pdfium.PdfDocument(filepath)
            except pdfium.PdfiumError:
                # Leave malformed/encrypted inputs to the normal Docling error
                # handling, including the existing Ghostscript repair fallback.
                document = None
            if document is not None:
                with document:
                    changed = 0
                    for index in range(len(document)):
                        with closing(document[index]) as page:
                            left, bottom, right, top = page.get_bbox()
                            width, height = right - left, top - bottom
                            if max(width, height) <= _MAX_PAGE_POINTS:
                                continue
                            scale = _MAX_PAGE_POINTS / max(width, height)
                            matrix = pdfium.raw.FS_MATRIX(
                                scale, 0, 0, scale, -left * scale, -bottom * scale
                            )
                            if not pdfium.raw.FPDFPage_TransFormWithClip(
                                page, matrix, None
                            ):
                                raise RuntimeError(
                                    "Could not scale oversized PDF page"
                                )
                            pdfium.raw.FPDFPage_TransformAnnots(
                                page, scale, 0, 0, scale,
                                -left * scale, -bottom * scale,
                            )
                            bounds = (0, 0, width * scale, height * scale)
                            page.set_mediabox(*bounds)
                            page.set_cropbox(*bounds)
                            page.set_trimbox(*bounds)
                            page.set_bleedbox(*bounds)
                            page.set_artbox(*bounds)
                            changed += 1
                    if changed:
                        with tempfile.NamedTemporaryFile(
                            suffix=".pdf", delete=False
                        ) as tmp:
                            temporary_path = tmp.name
                        document.save(temporary_path)
                        logger.info(
                            "Scaled %s oversized PDF pages for conversion: %s "
                            "(original preserved)",
                            changed,
                            filepath,
                        )
        yield temporary_path or filepath
    finally:
        if temporary_path is not None:
            os.remove(temporary_path)


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

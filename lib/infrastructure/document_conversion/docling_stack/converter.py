"""Format routing for the repository's Docling-centred conversion stack."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from lib.infrastructure.document_conversion.docling_stack.docling import (
    convert_document as convert_with_docling,
    convert_document_force_ocr,
)
from lib.infrastructure.document_conversion.docling_stack.pdf import (
    repair_pdf,
)
from lib.infrastructure.document_conversion.docling_stack.rtf import convert_rtf
from lib.infrastructure.document_conversion.docling_stack.spreadsheets import (
    convert_spreadsheet,
    is_spreadsheet_filename,
)
from lib.infrastructure.document_conversion.normalization import (
    has_dense_private_use_encoding,
)
from lib.infrastructure.document_conversion.types import DocumentConversion
from lib.infrastructure.logging import get_logger
from lib.infrastructure.scheduler import scheduler
from lib.infrastructure.scheduler_operations import (
    JobProfile,
    register_operation,
)

logger = get_logger(__name__)

_PASSTHROUGH_EXTENSIONS = (".json", ".txt", ".md")
_RTF_EXTENSIONS = (".rtf",)
_UNSUPPORTED_EXTENSIONS = (".ai", ".eps")


async def convert_document(path: Path) -> DocumentConversion:
    """Convert one document using the Docling-centred local stack."""
    lower_name = path.name.lower()
    if lower_name.endswith(_UNSUPPORTED_EXTENSIONS):
        raise ValueError(f"Unsupported document format: {path.suffix}")
    if path.stat().st_size == 0:
        return DocumentConversion(
            markdown="",
            warnings=("The source file is empty",),
        )
    if lower_name.endswith(_PASSTHROUGH_EXTENSIONS):
        return DocumentConversion(
            markdown=await asyncio.to_thread(
                path.read_text,
                encoding="utf-8",
                errors="ignore",
            )
        )
    if lower_name.endswith(_RTF_EXTENSIONS):
        return DocumentConversion(
            markdown=await asyncio.to_thread(convert_rtf, str(path))
        )
    if is_spreadsheet_filename(path.name):
        return await asyncio.to_thread(convert_spreadsheet, path)
    return await _convert_with_docling(path)


async def _scheduled_docling_call(
    operation: Callable[[str], str],
    path: Path,
) -> str:
    return await scheduler.run(
        _execute_docling,
        operation_kwargs={
            "filepath": str(path),
            "force_ocr": operation is convert_document_force_ocr,
        },
    )


def _execute_docling(*, filepath: str, force_ocr: bool) -> str:
    operation = convert_document_force_ocr if force_ocr else convert_with_docling
    return operation(filepath)


def _inspect_docling(kwargs: Mapping[str, Any]) -> JobProfile:
    path = Path(str(kwargs["filepath"]))
    force_ocr = bool(kwargs["force_ocr"])
    return JobProfile(
        kind="docling_ocr" if force_ocr else "docling",
        descriptor="docling",
        input_size=path.stat().st_size,
        parameters={
            "mode": "full_page_ocr" if force_ocr else "standard",
            "extension": path.suffix.lower(),
        },
    )


register_operation(_execute_docling, _inspect_docling)


async def _convert_with_docling(path: Path) -> DocumentConversion:
    warnings: list[str] = []
    try:
        markdown = await _scheduled_docling_call(convert_with_docling, path)
        if path.suffix.lower() == ".pdf" and has_dense_private_use_encoding(
            markdown
        ):
            logger.warning(
                "Detected high-density private-use font encoding in %s; "
                "retrying with full-page OCR",
                path.name,
            )
            markdown = await _scheduled_docling_call(
                convert_document_force_ocr,
                path,
            )
            warnings.append("Full-page OCR was required")
            if has_dense_private_use_encoding(markdown):
                raise RuntimeError(
                    "Full-page OCR still produced high-density "
                    "private-use characters"
                )
        return DocumentConversion(
            markdown=markdown,
            warnings=tuple(warnings),
        )
    except Exception as error:
        if path.suffix.lower() != ".pdf" or "page-dimensions" not in str(
            error
        ):
            raise
        logger.warning(
            "Docling could not resolve page dimensions for %s; "
            "retrying after Ghostscript normalization",
            path.name,
        )
        repaired_path = Path(await asyncio.to_thread(repair_pdf, str(path)))
        try:
            markdown = await _scheduled_docling_call(
                convert_with_docling,
                repaired_path,
            )
        finally:
            await asyncio.to_thread(repaired_path.unlink, missing_ok=True)
        return DocumentConversion(
            markdown=markdown,
            warnings=("The PDF required Ghostscript normalization",),
        )

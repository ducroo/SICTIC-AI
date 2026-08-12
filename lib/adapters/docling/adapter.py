from __future__ import annotations

import asyncio
import os
from typing import List

from lib.adapters.docling.converter import (
    convert_document,
    convert_document_force_ocr,
)
from lib.adapters.docling.pdf import convert_repaired_pdf
from lib.adapters.docling.rtf import convert_rtf
from lib.adapters.docling.spreadsheets import (
    convert_spreadsheet,
    is_spreadsheet_filename,
)
from lib.adapters.docling.types import (
    ConversionStatus,
    DocumentConversionResult,
)
from lib.datasets.text_normalization import has_dense_private_use_encoding
from lib.logger import get_logger

logger = get_logger(__name__)

_PASSTHROUGH_EXTENSIONS = (".json", ".txt", ".md")
_RTF_EXTENSIONS = (".rtf",)
_UNSUPPORTED_EXTENSIONS = (".ai", ".eps")


class DoclingAdapter:
    def __init__(self, concurrency_limit: int | None = None):
        self.concurrency_limit = concurrency_limit

    async def extract_documents(self, files_to_process: List[dict]):
        tasks = []
        for file_data in files_to_process:
            filename = file_data["filename"]
            filepath = str(file_data["local_path"])

            async def run(fname=filename, path=filepath):
                if fname.lower().endswith(_UNSUPPORTED_EXTENSIONS):
                    return DocumentConversionResult(
                        filename=fname,
                        status=ConversionStatus.IGNORED_EMPTY,
                        reason="unsupported_format",
                    )
                try:
                    text = await self._process_single_file(
                        path,
                        fname,
                        raise_on_error=True,
                    )
                    status = (
                        ConversionStatus.SUCCESS
                        if text
                        else ConversionStatus.IGNORED_EMPTY
                    )
                    reason = ""
                    if not text:
                        reason = (
                            "empty_source"
                            if os.path.getsize(path) == 0
                            else "no_extractable_text"
                        )
                    return DocumentConversionResult(
                        filename=fname,
                        status=status,
                        text=text,
                        reason=reason,
                    )
                except Exception as error:
                    if _is_unsupported_format_error(error):
                        return DocumentConversionResult(
                            filename=fname,
                            status=ConversionStatus.IGNORED_EMPTY,
                            reason="unsupported_format",
                        )
                    return DocumentConversionResult(
                        filename=fname,
                        status=ConversionStatus.FAILED,
                        error=_short_error(error),
                    )

            tasks.append(asyncio.create_task(run()))

        for task in asyncio.as_completed(tasks):
            yield await task

    async def _process_single_file(
        self,
        filepath: str,
        filename: str,
        *,
        raise_on_error: bool = False,
    ) -> str:
        from lib.services_gateway import gateway

        slot_kwargs = {"model": os.environ.get("VLM_MODEL") or "docling"}
        if self.concurrency_limit is not None:
            slot_kwargs["max_concurrent"] = self.concurrency_limit
        async with gateway.slot("docling", **slot_kwargs):
            if not os.path.isfile(filepath):
                logger.warning("Skipping %s, not a valid local file.", filepath)
                if raise_on_error:
                    raise FileNotFoundError(filepath)
                return ""
            if os.path.getsize(filepath) == 0:
                logger.warning(
                    "Skipping %s, file is empty (0 bytes).",
                    filepath,
                )
                return ""

            lower_name = filename.lower()
            if lower_name.endswith(_PASSTHROUGH_EXTENSIONS):
                with open(
                    filepath,
                    "r",
                    encoding="utf-8",
                    errors="ignore",
                ) as handle:
                    return handle.read()
            if lower_name.endswith(_RTF_EXTENSIONS):
                return await asyncio.to_thread(
                    self._convert_rtf_sync,
                    filepath,
                )
            if is_spreadsheet_filename(filename):
                return await asyncio.to_thread(
                    self._convert_spreadsheet_sync,
                    filepath,
                )

            try:
                text = await asyncio.to_thread(
                    self._convert_sync,
                    filepath,
                )
                if (
                    lower_name.endswith(".pdf")
                    and has_dense_private_use_encoding(text)
                ):
                    logger.warning(
                        "Detected high-density private-use font encoding in "
                        "%s. Retrying with full-page OCR.",
                        filename,
                    )
                    text = await asyncio.to_thread(
                        self._convert_force_ocr_sync,
                        filepath,
                    )
                    if has_dense_private_use_encoding(text):
                        raise RuntimeError(
                            "Full-page OCR still produced high-density "
                            "private-use characters."
                        )
                return text
            except Exception as error:
                if lower_name.endswith(".pdf") and "page-dimensions" in str(
                    error
                ):
                    logger.warning(
                        "Docling conversion failed for %s: could not resolve "
                        "page dimensions. Retrying after Ghostscript PDF "
                        "normalization.",
                        filename,
                    )
                    try:
                        return await asyncio.to_thread(
                            self._convert_repaired_pdf_sync,
                            filepath,
                        )
                    except Exception as repair_error:
                        logger.error(
                            "Docling conversion failed for %s after "
                            "Ghostscript normalization: %s",
                            filename,
                            _short_error(repair_error),
                        )
                        if raise_on_error:
                            raise
                        return ""
                logger.error(
                    "Docling conversion failed for %s: %s",
                    filename,
                    _short_error(error),
                )
                if raise_on_error:
                    raise
                return ""

    @staticmethod
    def _convert_sync(filepath: str) -> str:
        return convert_document(filepath)

    @staticmethod
    def _convert_force_ocr_sync(filepath: str) -> str:
        return convert_document_force_ocr(filepath)

    @staticmethod
    def _convert_rtf_sync(filepath: str) -> str:
        return convert_rtf(filepath)

    @staticmethod
    def _convert_repaired_pdf_sync(filepath: str) -> str:
        return convert_repaired_pdf(filepath, DoclingAdapter._convert_sync)

    @staticmethod
    def _convert_spreadsheet_sync(filepath: str) -> str:
        return convert_spreadsheet(filepath)


def _short_error(error: Exception, limit: int = 500) -> str:
    text = str(error).replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _is_unsupported_format_error(error: Exception) -> bool:
    text = str(error)
    return (
        "File format not allowed" in text
        or "does not match any allowed format" in text
    )

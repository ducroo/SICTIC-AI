from __future__ import annotations

import asyncio
import os
from typing import List

from lib.adapters.docling.converter import convert_document
from lib.adapters.docling.pdf import convert_repaired_pdf
from lib.adapters.docling.rtf import convert_rtf
from lib.adapters.docling.spreadsheets import (
    convert_openpyxl,
    convert_spreadsheet,
    convert_xls,
    is_spreadsheet_filename,
)
from lib.adapters.docling.types import (
    ConversionStatus,
    DocumentConversionResult,
)
from lib.logger import get_logger

logger = get_logger(__name__)

_PASSTHROUGH_EXTENSIONS = (".json", ".txt", ".md")
_RTF_EXTENSIONS = (".rtf",)


class DoclingAdapter:
    def __init__(self, concurrency_limit: int = 10):
        self.concurrency_limit = concurrency_limit

    async def extract_documents(self, files_to_process: List[dict]):
        tasks = []
        for file_data in files_to_process:
            filename = file_data["filename"]
            filepath = str(file_data["local_path"])

            async def run(fname=filename, path=filepath):
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

        async with gateway.slot(
            "docling",
            max_concurrent=self.concurrency_limit,
        ):
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
                return await asyncio.to_thread(
                    self._convert_sync,
                    filepath,
                )
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
    def _convert_rtf_sync(filepath: str) -> str:
        return convert_rtf(filepath)

    @staticmethod
    def _convert_repaired_pdf_sync(filepath: str) -> str:
        return convert_repaired_pdf(filepath, DoclingAdapter._convert_sync)

    @staticmethod
    def _convert_spreadsheet_sync(filepath: str) -> str:
        return convert_spreadsheet(filepath)

    @staticmethod
    def _convert_openpyxl_sync(filepath: str) -> str:
        return convert_openpyxl(filepath)

    @staticmethod
    def _convert_xls_sync(filepath: str) -> str:
        return convert_xls(filepath)


def _short_error(error: Exception, limit: int = 500) -> str:
    text = str(error).replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text

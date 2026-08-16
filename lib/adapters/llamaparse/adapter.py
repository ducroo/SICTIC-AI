"""LlamaParse SaaS adapter with the same surface as DoclingAdapter."""

from __future__ import annotations

import asyncio
import os
from typing import List

from lib.adapters.docling.rtf import convert_rtf
from lib.adapters.docling.spreadsheets import (
    convert_spreadsheet,
    is_spreadsheet_filename,
)
from lib.adapters.docling.types import (
    ConversionStatus,
    DocumentConversionResult,
)
from lib.datasets.page_markers import format_page_marker
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

_PASSTHROUGH_EXTENSIONS = (".json", ".txt", ".md")
_RTF_EXTENSIONS = (".rtf",)
_UNSUPPORTED_EXTENSIONS = (".ai", ".eps")


class LlamaParseAdapter:
    """Convert source files to Markdown via LlamaCloud Parse."""

    def __init__(self, concurrency_limit: int | None = None):
        self.concurrency_limit = concurrency_limit
        self._tier = (
            os.environ.get("LLAMA_PARSE_TIER") or "cost_effective"
        ).strip()
        self._version = (
            os.environ.get("LLAMA_PARSE_VERSION") or "latest"
        ).strip()

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
                    text = await self._process_single_file(path, fname)
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
                        error=str(error),
                    )

            tasks.append(run())

        if not tasks:
            return

        limit = self.concurrency_limit or len(tasks)
        semaphore = asyncio.Semaphore(max(1, limit))

        async def guarded(coro):
            async with semaphore:
                return await coro

        for coro in asyncio.as_completed([guarded(task) for task in tasks]):
            yield await coro

    async def _process_single_file(self, filepath: str, filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(_PASSTHROUGH_EXTENSIONS):
            with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read().strip()
        if lower.endswith(_RTF_EXTENSIONS):
            return await asyncio.to_thread(convert_rtf, filepath)
        if is_spreadsheet_filename(filename):
            return await asyncio.to_thread(convert_spreadsheet, filepath)
        return await self._parse_with_llamacloud(filepath, filename)

    async def _parse_with_llamacloud(self, filepath: str, filename: str) -> str:
        # Ensure the key is present before importing the SDK.
        get_env_var("LLAMA_CLOUD_API_KEY")
        try:
            from llama_cloud import AsyncLlamaCloud
        except ImportError as error:
            raise RuntimeError(
                "llama-cloud is required for DOCUMENT_PARSER=llamaparse. "
                "Install it into sictic-env (see environment.yml)."
            ) from error

        client = AsyncLlamaCloud()
        uploaded = await client.files.create(file=filepath, purpose="parse")
        result = await client.parsing.parse(
            file_id=uploaded.id,
            tier=self._tier,
            version=self._version,
            expand=["markdown"],
        )
        markdown = _markdown_from_parse_result(result)
        if not markdown.strip():
            logger.warning(
                "LlamaParse returned empty markdown for %s (tier=%s).",
                filename,
                self._tier,
            )
        return markdown.strip()


def _markdown_from_parse_result(result) -> str:
    markdown = getattr(result, "markdown", None)
    if markdown is None:
        return ""
    pages = getattr(markdown, "pages", None) or []
    sections: list[str] = []
    for index, page in enumerate(pages, start=1):
        page_text = getattr(page, "markdown", None) or getattr(page, "text", "") or ""
        page_text = str(page_text).strip()
        if not page_text:
            continue
        sections.append(f"{format_page_marker(index)}\n\n{page_text}")
    if sections:
        return "\n\n".join(sections)
    # Some SDK shapes expose a top-level markdown string.
    fallback = getattr(markdown, "markdown", None) or getattr(markdown, "text", None)
    return str(fallback or "").strip()

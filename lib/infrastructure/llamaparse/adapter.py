"""LlamaParse SaaS conversion backend."""  # pragma: allowlist secret

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from lib.datasets.page_markers import format_page_marker
from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.document_conversion.docling_stack.rtf import convert_rtf
from lib.infrastructure.document_conversion.docling_stack.spreadsheets import (
    convert_spreadsheet,
    is_spreadsheet_filename,
)
from lib.infrastructure.document_conversion.types import DocumentConversion
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

_PASSTHROUGH_EXTENSIONS = (".json", ".txt", ".md")
_RTF_EXTENSIONS = (".rtf",)
_UNSUPPORTED_EXTENSIONS = (".ai", ".eps")


async def convert_document(path: Path) -> DocumentConversion:
    """Convert one document via LlamaCloud Parse, with local passthrough."""
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
    markdown = await _parse_with_llamacloud(path)
    return DocumentConversion(markdown=markdown)


async def _parse_with_llamacloud(path: Path) -> str:
    get_env_var("LLAMA_CLOUD_API_KEY")
    try:
        from llama_cloud import AsyncLlamaCloud
    except ImportError as error:
        raise RuntimeError(
            "llama-cloud is required for DOCUMENT_PARSER=llamaparse. "  # pragma: allowlist secret
            "Install it into sictic-env (see environment.yml)."
        ) from error

    tier = (os.environ.get("LLAMA_PARSE_TIER") or "cost_effective").strip()
    version = (os.environ.get("LLAMA_PARSE_VERSION") or "latest").strip()
    client = AsyncLlamaCloud()
    uploaded = await client.files.create(file=str(path), purpose="parse")
    result = await client.parsing.parse(
        file_id=uploaded.id,
        tier=tier,
        version=version,
        expand=["markdown"],
    )
    markdown = _markdown_from_parse_result(result)
    if not markdown.strip():
        logger.warning(
            "Parse returned empty markdown for %s (tier=%s).",
            path.name,
            tier,
        )
    return markdown.strip()


def _markdown_from_parse_result(result) -> str:
    markdown = getattr(result, "markdown", None)
    if markdown is None:
        return ""
    pages = getattr(markdown, "pages", None) or []
    sections: list[str] = []
    for index, page in enumerate(pages, start=1):
        page_text = (
            getattr(page, "markdown", None) or getattr(page, "text", "") or ""
        )
        page_text = str(page_text).strip()
        if not page_text:
            continue
        sections.append(f"{format_page_marker(index)}\n\n{page_text}")
    if sections:
        return "\n\n".join(sections)
    fallback = getattr(markdown, "markdown", None) or getattr(
        markdown, "text", None
    )
    return str(fallback or "").strip()

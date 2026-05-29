"""
DoclingAdapter — thin wrapper around the docling library for OCR/parsing.

Runs in-process. No HTTP, no separate server. Models load on first call and
are reused for the lifetime of the process via a module-level singleton.

OCR backend: Apple Vision via ocrmac on macOS; RapidOCR on Linux.
Picture descriptions: forwarded to Ollama's OpenAI-compatible endpoint, same
as the previous docling-serve setup.
"""
import asyncio
import os
import platform
import threading
from typing import List

from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

_PASSTHROUGH_EXTS = (".json", ".txt", ".md")

_converter = None
_converter_init_lock = threading.Lock()
# docling's pipeline objects aren't documented as thread-safe; serialise convert() calls.
_convert_lock = threading.Lock()


def _build_converter():
    """Construct the DocumentConverter — called once, lazily."""
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        PictureDescriptionApiOptions,
        OcrMacOptions,
        RapidOcrOptions,
    )

    vlm_model_name = get_env_var("DEFAULT_VLM")
    if vlm_model_name.startswith("ollama/"):
        vlm_model_name = vlm_model_name[7:]
    ollama_url = get_env_var("OLLAMA_HOST").rstrip("/")

    if platform.system() == "Darwin":
        ocr_options = OcrMacOptions()
    else:
        ocr_options = RapidOcrOptions()

    pipeline_opts = PdfPipelineOptions(
        do_ocr=True,
        do_picture_description=True,
        enable_remote_services=True,  # needed for picture_description_options below
        ocr_options=ocr_options,
        picture_description_options=PictureDescriptionApiOptions(
            url=f"{ollama_url}/v1/chat/completions",
            params={"model": vlm_model_name, "max_tokens": 200},
            prompt="Describe this image in a few sentences.",
            timeout=600,
        ),
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
    )


def _get_converter():
    global _converter
    if _converter is not None:
        return _converter
    with _converter_init_lock:
        if _converter is None:
            logger.info("Initializing docling DocumentConverter (first use; models load on first convert)")
            _converter = _build_converter()
    return _converter


class DoclingAdapter:
    def __init__(self, concurrency_limit: int = 10):
        self.concurrency_limit = concurrency_limit

    async def extract_documents(self, files_to_process: List[dict]):
        """Yield (filename, markdown) for each file as conversion finishes.

        Each item in files_to_process must include:
          - "filename": the logical name used in returned tuples and downstream paths
          - "local_path": an on-disk absolute path docling can open (use
            storage.local_path(rel) to materialize a Drive file locally first).
        """
        tasks = []
        for f_data in files_to_process:
            filename = f_data["filename"]
            filepath = str(f_data["local_path"])

            async def run(fname=filename, fp=filepath):
                txt = await self._process_single_file(fp, fname)
                return fname, txt

            tasks.append(asyncio.create_task(run()))

        for coro in asyncio.as_completed(tasks):
            yield await coro

    async def _process_single_file(self, filepath: str, filename: str) -> str:
        from lib.services_gateway import gateway

        await gateway.acquire_docling_slot(self.concurrency_limit)
        try:
            if not os.path.isfile(filepath):
                logger.warning(f"Skipping {filepath}, not a valid local file.")
                return ""
            if os.path.getsize(filepath) == 0:
                logger.warning(f"Skipping {filepath}, file is empty (0 bytes).")
                return ""

            if filename.lower().endswith(_PASSTHROUGH_EXTS):
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()

            try:
                return await asyncio.to_thread(self._convert_sync, filepath)
            except Exception as e:
                logger.error(f"Docling conversion failed for {filename}: {e}")
                return ""
        finally:
            gateway.release_docling_slot()

    @staticmethod
    def _convert_sync(filepath: str) -> str:
        converter = _get_converter()
        with _convert_lock:
            result = converter.convert(filepath)
        return result.document.export_to_markdown()

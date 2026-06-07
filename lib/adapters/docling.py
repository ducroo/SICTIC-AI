"""
DoclingAdapter — thin wrapper around the docling library for OCR/parsing.

Runs in-process. No HTTP, no separate server. Models load on first call and
are reused for the lifetime of the process via a module-level singleton.

OCR backend: Apple Vision via ocrmac on macOS; RapidOCR on Linux.
Picture descriptions are forwarded to a configured VLM service.
"""
import asyncio
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from typing import List
from urllib.parse import urlparse

from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

_PASSTHROUGH_EXTS = (".json", ".txt", ".md")
_SPREADSHEET_EXTS = (".xlsx", ".xlsm")
_EXCEL_MAX_COLUMNS = 16_384
_WIDE_MERGE_FALLBACK_COLUMNS = 1_024
_WIDE_SHEET_FALLBACK_CELLS = 250_000

_converter = None
_converter_init_lock = threading.Lock()
# docling's pipeline objects aren't documented as thread-safe; serialise convert() calls.
_convert_lock = threading.Lock()


def _build_converter():
    """Construct the DocumentConverter — called once, lazily."""
    from lib.runtime_noise import configure_runtime_noise

    configure_runtime_noise()

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        PictureDescriptionApiOptions,
        OcrMacOptions,
        RapidOcrOptions,
    )

    vlm_model_name = get_env_var("VLM_MODEL")
    vlm_base_url = (
        os.environ.get("VLM_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://localhost:11434"
    ).rstrip("/")
    vlm_model_name = _chat_completions_model(vlm_base_url, vlm_model_name)
    vlm_api_key = os.environ.get("VLM_API_KEY") or os.environ.get("LLM_API_KEY") or ""
    headers = {"Authorization": f"Bearer {vlm_api_key}"} if vlm_api_key else {}

    if platform.system() == "Darwin":
        ocr_options = OcrMacOptions()
    else:
        ocr_options = RapidOcrOptions()

    pipeline_opts = PdfPipelineOptions(
        do_ocr=True,
        do_picture_description=True,
        enable_remote_services=True,
        ocr_options=ocr_options,
        picture_description_options=PictureDescriptionApiOptions(
            url=_chat_completions_url(vlm_base_url),
            headers=headers,
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
                if filename.lower().endswith(_SPREADSHEET_EXTS) and await asyncio.to_thread(
                    self._spreadsheet_needs_compact_fallback, filepath
                ):
                    logger.warning(
                        f"Using compact spreadsheet conversion for {filename}: "
                        "workbook contains very wide merged/formatted ranges."
                    )
                    return await asyncio.to_thread(self._convert_spreadsheet_sync, filepath)
                return await asyncio.to_thread(self._convert_sync, filepath)
            except Exception as e:
                if filename.lower().endswith(_SPREADSHEET_EXTS):
                    logger.warning(
                        f"Docling conversion failed for {filename}: {e}. "
                        "Retrying with compact spreadsheet conversion."
                    )
                    return await asyncio.to_thread(self._convert_spreadsheet_sync, filepath)
                if filename.lower().endswith(".pdf") and "page-dimensions" in str(e):
                    logger.warning(
                        f"Docling conversion failed for {filename}: could not resolve page dimensions. "
                        "Retrying after Ghostscript PDF normalization."
                    )
                    try:
                        return await asyncio.to_thread(self._convert_repaired_pdf_sync, filepath)
                    except Exception as repair_error:
                        logger.error(
                            f"Docling conversion failed for {filename} after Ghostscript normalization: "
                            f"{_short_error(repair_error)}"
                        )
                        return ""
                logger.error(f"Docling conversion failed for {filename}: {_short_error(e)}")
                return ""
        finally:
            gateway.release_docling_slot()

    @staticmethod
    def _convert_sync(filepath: str) -> str:
        converter = _get_converter()
        with _convert_lock:
            result = converter.convert(filepath)
        return result.document.export_to_markdown()

    @staticmethod
    def _convert_repaired_pdf_sync(filepath: str) -> str:
        gs = shutil.which("gs")
        if not gs:
            raise RuntimeError("Ghostscript executable 'gs' not found.")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            repaired_path = tmp.name
        try:
            subprocess.run(
                [
                    gs,
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
            return DoclingAdapter._convert_sync(repaired_path)
        finally:
            try:
                os.remove(repaired_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def _convert_spreadsheet_sync(filepath: str) -> str:
        """Convert pathological spreadsheets without exporting formatted empty grid areas."""
        from openpyxl import load_workbook

        values_wb = load_workbook(filepath, read_only=False, data_only=True)
        formulas_wb = load_workbook(filepath, read_only=False, data_only=False)
        sections = []

        for values_ws, formulas_ws in zip(values_wb.worksheets, formulas_wb.worksheets):
            row_cells: dict[int, dict[int, str]] = {}
            for row, col in set(values_ws._cells.keys()) | set(formulas_ws._cells.keys()):
                value = values_ws.cell(row=row, column=col).value
                if value in (None, ""):
                    value = formulas_ws.cell(row=row, column=col).value
                text = "" if value is None else str(value).replace("\n", " ").strip()
                if text:
                    row_cells.setdefault(row, {})[col] = text

            if not row_cells:
                continue

            sections.append(f"## {values_ws.title}")
            for row_idx in sorted(row_cells):
                cols = row_cells[row_idx]
                max_col = max(cols)
                row = [cols.get(col_idx, "") for col_idx in range(1, max_col + 1)]
                sections.append("| " + " | ".join(_escape_markdown_cell(c) for c in row) + " |")
            sections.append("")

        return "\n".join(sections).strip() + "\n"

    @staticmethod
    def _spreadsheet_needs_compact_fallback(filepath: str) -> bool:
        """Detect Excel files that Docling expands to enormous mostly-empty tables.

        Docling's Excel backend correctly ignores ordinary empty worksheet area, but it
        treats merged ranges as real table bounds. Some financial models contain
        cosmetic full-row merges such as A:XFD; exporting those through Docling can turn
        a small workbook into tens of MB of markdown. Use the compact fallback only for
        those pathological sheets so normal spreadsheets still use Docling.
        """
        from openpyxl import load_workbook

        workbook = load_workbook(filepath, read_only=False, data_only=True)
        for sheet in workbook.worksheets:
            for merged_range in sheet.merged_cells.ranges:
                if merged_range.max_col >= _EXCEL_MAX_COLUMNS:
                    return True
                if merged_range.max_col - merged_range.min_col + 1 >= _WIDE_MERGE_FALLBACK_COLUMNS:
                    return True

            if sheet.max_row * sheet.max_column >= _WIDE_SHEET_FALLBACK_CELLS:
                value_cols = {
                    cell.column
                    for cell in sheet._cells.values()
                    if cell.value not in (None, "")
                }
                if value_cols and sheet.max_column > max(value_cols) * 10:
                    return True

        return False


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _short_error(error: Exception, limit: int = 500) -> str:
    text = str(error).replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _chat_completions_model(base_url: str, model: str) -> str:
    if model.startswith("ollama/") and _is_ollama_base_url(base_url):
        return model[7:]
    return model


def _is_ollama_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"} and parsed.port == 11434

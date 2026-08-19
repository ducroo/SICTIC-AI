from __future__ import annotations

import os
import platform
import threading
from urllib.parse import urlparse

from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

_converter = None
_force_ocr_converter = None
_converter_init_lock = threading.Lock()
_convert_lock = threading.Lock()


def build_converter(*, force_full_page_ocr: bool = False):
    """Construct the Docling converter with platform-appropriate OCR."""
    from lib.runtime_noise import configure_runtime_noise

    configure_runtime_noise()

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        OcrMacOptions,
        PdfPipelineOptions,
        PictureDescriptionApiOptions,
        RapidOcrOptions,
    )

    vlm_model = get_env_var("VLM_MODEL")
    vlm_base_url = (
        os.environ.get("VLM_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://localhost:11434"
    ).rstrip("/")
    vlm_model = chat_completions_model(vlm_base_url, vlm_model)
    api_key = (
        os.environ.get("VLM_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    ocr_options = (
        OcrMacOptions(force_full_page_ocr=force_full_page_ocr)
        if platform.system() == "Darwin"
        else RapidOcrOptions(force_full_page_ocr=force_full_page_ocr)
    )
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_picture_description=True,
        enable_remote_services=True,
        ocr_options=ocr_options,
        picture_description_options=PictureDescriptionApiOptions(
            url=chat_completions_url(vlm_base_url),
            headers=headers,
            params=picture_description_params(vlm_model),
            prompt="Describe this image in a few sentences.",
            timeout=600,
        ),
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options
            )
        }
    )


def get_converter():
    global _converter
    if _converter is not None:
        return _converter
    with _converter_init_lock:
        if _converter is None:
            logger.info(
                "Initializing docling DocumentConverter "
                "(first use; models load on first convert)"
            )
            _converter = build_converter()
    return _converter


def get_force_ocr_converter():
    global _force_ocr_converter
    if _force_ocr_converter is not None:
        return _force_ocr_converter
    with _converter_init_lock:
        if _force_ocr_converter is None:
            logger.info(
                "Initializing full-page OCR Docling DocumentConverter"
            )
            _force_ocr_converter = build_converter(force_full_page_ocr=True)
    return _force_ocr_converter


def export_document_markdown(document) -> str:
    """Export Markdown with explicit page markers when Docling has page data."""
    from lib.datasets.page_markers import format_page_marker

    page_numbers = sorted(document.pages.keys())
    if not page_numbers:
        return document.export_to_markdown()

    if len(page_numbers) == 1:
        page_no = page_numbers[0]
        body = document.export_to_markdown().strip()
        if not body:
            return ""
        return f"{format_page_marker(page_no)}\n\n{body}"

    parts: list[str] = []
    for page_no in page_numbers:
        page_md = document.export_to_markdown(page_no=page_no).strip()
        if page_md:
            parts.append(f"{format_page_marker(page_no)}\n\n{page_md}")
    if parts:
        return "\n\n".join(parts)
    return document.export_to_markdown()


def convert_document(filepath: str) -> str:
    converter = get_converter()
    with _convert_lock:
        result = converter.convert(filepath)
    return export_document_markdown(result.document)


def convert_document_force_ocr(filepath: str) -> str:
    converter = get_force_ocr_converter()
    with _convert_lock:
        result = converter.convert(filepath)
    return export_document_markdown(result.document)


def picture_description_params(model: str) -> dict[str, object]:
    """Chat-completions extras for Docling picture descriptions.

    Newer OpenAI models (including gpt-5.6-luna) reject `max_tokens` and
    require `max_completion_tokens`.
    """
    return {"model": model, "max_completion_tokens": 200}


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def chat_completions_model(base_url: str, model: str) -> str:
    if model.startswith("ollama/") and _is_ollama_base_url(base_url):
        return model[7:]
    return model


def _is_ollama_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    return (
        host in {"localhost", "127.0.0.1", "::1"}
        and parsed.port == 11434
    )

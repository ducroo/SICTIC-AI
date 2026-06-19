from __future__ import annotations

import os
import platform
import threading
from urllib.parse import urlparse

from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

_converter = None
_converter_init_lock = threading.Lock()
_convert_lock = threading.Lock()


def build_converter():
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
        or ""
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    ocr_options = (
        OcrMacOptions()
        if platform.system() == "Darwin"
        else RapidOcrOptions()
    )
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_picture_description=True,
        enable_remote_services=True,
        ocr_options=ocr_options,
        picture_description_options=PictureDescriptionApiOptions(
            url=chat_completions_url(vlm_base_url),
            headers=headers,
            params={"model": vlm_model, "max_tokens": 200},
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


def convert_document(filepath: str) -> str:
    converter = get_converter()
    with _convert_lock:
        result = converter.convert(filepath)
    return result.document.export_to_markdown()


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

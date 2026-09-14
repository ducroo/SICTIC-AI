"""Convert documents through a remote Docling Serve HTTP API.

Selected with DOCUMENT_CONVERTER=docling_serve. Talks to DOCLING_SERVE_URL.
Renders the JSON graph to Markdown on CPU. Spreadsheets and RTF stay local.
The spike image keeps using HTTP only. It does not install Docling.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import requests

from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.document_conversion.docling_stack.rtf import convert_rtf
from lib.infrastructure.document_conversion.docling_stack.spreadsheets import (
    convert_spreadsheet,
    is_spreadsheet_filename,
)
from lib.infrastructure.document_conversion.graph_markdown import graph_to_markdown
from lib.infrastructure.document_conversion.types import DocumentConversion
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

DOCLING_SERVE_CONVERTER = "docling_serve"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_POLL_INTERVAL_S = 2.0
SUBMIT_TIMEOUT_S = 60.0
STATUS_TIMEOUT_S = 30.0

_PASSTHROUGH_EXTENSIONS = (".json", ".txt", ".md")
_RTF_EXTENSIONS = (".rtf",)
_UNSUPPORTED_EXTENSIONS = (".ai", ".eps")

QUALITY_CONVERT_OPTIONS = {
    "to_formats": ["json", "md"],
    "do_ocr": True,
    "table_mode": "accurate",
    "do_table_structure": True,
    "do_pdf_heading_hierarchy": True,
    "image_export_mode": "placeholder",
    "include_images": False,
    "include_page_images": False,
}


def serve_base_url() -> str:
    return get_env_var("DOCLING_SERVE_URL").rstrip("/")


def convert_timeout_s() -> float:
    raw = get_env_var("DOCLING_SERVE_TIMEOUT", required=False)
    if raw is None:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError as error:
        raise InfrastructureError(
            "DOCLING_SERVE_TIMEOUT must be numeric",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider=DOCLING_SERVE_CONVERTER,
            operation="load_configuration",
        ) from error
    if value <= 0:
        raise InfrastructureError(
            "DOCLING_SERVE_TIMEOUT must be positive",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider=DOCLING_SERVE_CONVERTER,
            operation="load_configuration",
        )
    return value


def poll_interval_s() -> float:
    raw = get_env_var("DOCLING_SERVE_POLL_INTERVAL", required=False)
    if raw is None:
        return DEFAULT_POLL_INTERVAL_S
    try:
        value = float(raw)
    except ValueError as error:
        raise InfrastructureError(
            "DOCLING_SERVE_POLL_INTERVAL must be numeric",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider=DOCLING_SERVE_CONVERTER,
            operation="load_configuration",
        ) from error
    if value <= 0:
        raise InfrastructureError(
            "DOCLING_SERVE_POLL_INTERVAL must be positive",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider=DOCLING_SERVE_CONVERTER,
            operation="load_configuration",
        )
    return value


def convert_form_fields(options: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key, value in options.items():
        if value is None:
            continue
        if isinstance(value, bool):
            fields.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            for item in value:
                fields.append((key, str(item)))
        else:
            fields.append((key, str(value)))
    return fields


def parse_json_content(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_convert_payload(
    payload: Any,
) -> tuple[str, dict[str, Any] | None, Any]:
    if not isinstance(payload, dict):
        return "", None, None
    document = payload.get("document") or {}
    if not isinstance(document, dict):
        document = {}
    markdown = str(document.get("md_content") or document.get("text_content") or "")
    graph = parse_json_content(document.get("json_content"))
    return markdown, graph, payload.get("errors")


def persist_graph(source: Path, graph: dict[str, Any]) -> Path:
    sidecar = source.with_name(source.name + ".docling.json")
    sidecar.write_text(json.dumps(graph), encoding="utf-8")
    return sidecar


async def convert_document(path: Path) -> DocumentConversion:
    """Convert one document via Docling Serve, with local passthrough."""
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
    return await asyncio.to_thread(_convert_remote, path)


def _convert_remote(path: Path) -> DocumentConversion:
    base_url = serve_base_url()
    timeout_s = convert_timeout_s()
    options = dict(QUALITY_CONVERT_OPTIONS)
    options["document_timeout"] = timeout_s
    logger.info("Converting %s via Docling Serve at %s", path.name, base_url)
    payload = _submit_and_fetch(base_url, path, options, timeout_s)
    markdown, graph, errors = extract_convert_payload(payload)
    warnings: list[str] = []
    if errors:
        warnings.append(f"Docling Serve reported errors: {errors}")
    rendered = ""
    if graph:
        rendered = graph_to_markdown(graph).strip()
        try:
            persist_graph(path, graph)
        except OSError as error:
            warnings.append(f"Could not write Docling JSON sidecar: {error}")
    if rendered:
        return DocumentConversion(markdown=rendered, warnings=tuple(warnings))
    if markdown.strip():
        warnings.append("Docling Serve returned markdown without a JSON graph")
        return DocumentConversion(markdown=markdown, warnings=tuple(warnings))
    raise InfrastructureError(
        f"Docling Serve returned no document for {path.name}",
        kind=InfrastructureErrorKind.INVALID_RESPONSE,
        provider=DOCLING_SERVE_CONVERTER,
        operation="convert_document",
    )


def _submit_and_fetch(
    base_url: str,
    path: Path,
    options: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "accept": "application/json"}
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    started = time.monotonic()
    try:
        with path.open("rb") as handle:
            submit = requests.post(
                f"{base_url}/v1/convert/file/async",
                files={"files": (path.name, handle, mime)},
                data=convert_form_fields(options),
                headers=headers,
                timeout=SUBMIT_TIMEOUT_S,
                allow_redirects=False,
            )
    except requests.RequestException as error:
        raise InfrastructureError(
            f"Could not reach Docling Serve at {base_url}: {error}",
            kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
            provider=DOCLING_SERVE_CONVERTER,
            operation="submit_convert",
        ) from error
    payload = _json_or_error(submit, operation="submit_convert")
    task_id = payload.get("task_id") if isinstance(payload, dict) else None
    if not task_id:
        return payload
    task = _poll_task(base_url, str(task_id), timeout_s, headers, started)
    if str(task.get("task_status")) != "success":
        status = task.get("task_status") or "unknown"
        kind = (
            InfrastructureErrorKind.TIMEOUT
            if status == "timeout"
            else InfrastructureErrorKind.INVALID_RESPONSE
        )
        raise InfrastructureError(
            f"Docling Serve task {task_id} ended with {status}",
            kind=kind,
            provider=DOCLING_SERVE_CONVERTER,
            operation="poll_convert",
        )
    try:
        response = requests.get(
            f"{base_url}/v1/result/{task_id}",
            headers=headers,
            timeout=min(timeout_s, 120),
        )
    except requests.RequestException as error:
        raise InfrastructureError(
            f"Could not fetch Docling Serve result {task_id}: {error}",
            kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
            provider=DOCLING_SERVE_CONVERTER,
            operation="fetch_result",
        ) from error
    return _json_or_error(response, operation="fetch_result")


def _poll_task(
    base_url: str,
    task_id: str,
    timeout_s: float,
    headers: dict[str, str],
    started: float,
) -> dict[str, Any]:
    last: dict[str, Any] = {"task_id": task_id}
    while time.monotonic() - started < timeout_s:
        try:
            response = requests.get(
                f"{base_url}/v1/status/poll/{task_id}",
                headers=headers,
                timeout=STATUS_TIMEOUT_S,
            )
        except requests.RequestException as error:
            raise InfrastructureError(
                f"Could not poll Docling Serve task {task_id}: {error}",
                kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
                provider=DOCLING_SERVE_CONVERTER,
                operation="poll_convert",
            ) from error
        payload = _json_or_error(response, operation="poll_convert")
        if isinstance(payload, dict):
            last = payload
        status = str(last.get("task_status") or "")
        if status in {"success", "failure"}:
            return last
        time.sleep(poll_interval_s())
    last["task_status"] = last.get("task_status") or "timeout"
    return last


def _json_or_error(response: requests.Response, *, operation: str) -> dict[str, Any]:
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"detail": response.text[:300]}
    if not isinstance(payload, dict):
        payload = {"detail": str(payload)}
    if response.status_code >= 500:
        raise InfrastructureError(
            f"Docling Serve HTTP {response.status_code}: "
            f"{payload.get('detail') or payload}",
            kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
            provider=DOCLING_SERVE_CONVERTER,
            operation=operation,
        )
    if response.status_code >= 400:
        raise InfrastructureError(
            f"Docling Serve HTTP {response.status_code}: "
            f"{payload.get('detail') or payload}",
            kind=InfrastructureErrorKind.INVALID_RESPONSE,
            provider=DOCLING_SERVE_CONVERTER,
            operation=operation,
        )
    return payload

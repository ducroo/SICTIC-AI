"""Time a community Docling Serve pod: create, convert, terminate.

Loads RUNPOD_API_KEY from .env.runpod. Never prints the key. Always
terminates the pod, including on errors and signals.
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API = "https://api.runpod.io"
TEMPLATE_ID = "qgrb3e19va"
POD_NAME_PREFIX = "sictic-docling-kpi"
DEFAULT_ENV_FILE = Path("/workspace/.env.runpod")
DEFAULT_DISK_GB = 64
MIN_VRAM_GB = 16
SKIP_GPU_SUBSTRINGS = ("Tesla V100",)
USABLE_STOCK = frozenset({"LOW", "MEDIUM", "HIGH"})
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MINIMAL_PDF = b"""%PDF-1.1
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 68 >>stream
BT /F1 24 Tf 72 720 Td (SICTIC cloud smoke test) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
trailer<< /Root 1 0 R >>
%%EOF
"""

_active_pod_id: str | None = None
_session: requests.Session | None = None

READY_PATHS = ("/health", "/docs", "/openapi.json", "/ui")


class KpiFailed(RuntimeError):
    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


def load_api_key(env_path: Path) -> str:
    if not env_path.is_file():
        raise SystemExit(f"missing {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("RUNPOD_API_KEY=") and not line.strip().startswith("#"):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise SystemExit(f"RUNPOD_API_KEY is empty in {env_path}")


def api_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
    )
    return session


def rank_gpu_candidates(
    gpus: list[dict[str, Any]],
    *,
    min_memory: int = MIN_VRAM_GB,
    cloud: str = "COMMUNITY",
) -> list[dict[str, Any]]:
    """Cheapest usable GPUs first. Skip V100; the Docling image wants CUDA 12.x."""
    cloud_key = cloud.lower()
    ranked: list[dict[str, Any]] = []
    for gpu in gpus:
        gpu_id = str(gpu.get("id") or "")
        if not gpu_id or any(skip in gpu_id for skip in SKIP_GPU_SUBSTRINGS):
            continue
        memory = int(gpu.get("memory") or 0)
        if memory < min_memory:
            continue
        if cloud == "COMMUNITY" and not gpu.get("community"):
            continue
        if cloud == "SECURE" and not gpu.get("secure"):
            continue
        price = (gpu.get("price") or {}).get(cloud_key)
        if price is None:
            continue
        availability = gpu.get("availability")
        if availability not in USABLE_STOCK:
            continue
        data_centers = [
            str(item["id"])
            for item in (gpu.get("dataCenters") or [])
            if item.get("id") and item.get("availability") in USABLE_STOCK
        ]
        ranked.append(
            {
                "id": gpu_id,
                "memory": memory,
                "price": float(price),
                "availability": availability,
                "data_center_ids": data_centers,
            }
        )
    ranked.sort(key=lambda item: (item["price"], -item["memory"]))
    return ranked


def proxy_url(pod_id: str, port: int = 5001) -> str:
    return f"https://{pod_id}-{port}.proxy.runpod.net"


def collect_base_urls(pod: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    pod_id = pod.get("id")
    if pod_id:
        urls.append(proxy_url(str(pod_id)))
    runtime = pod.get("runtime") or {}
    for mapping in runtime.get("ports") or []:
        ip = mapping.get("ip")
        public = mapping.get("public")
        private = mapping.get("private")
        kind = str(mapping.get("type") or "")
        if private not in (5001, "5001"):
            continue
        if ip and public:
            scheme = "https" if kind == "http" else "http"
            urls.append(f"{scheme}://{ip}:{public}")
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def _json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"status": response.status_code, "text": response.text[:500]}


def list_pods(session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(f"{API}/v2/pods", timeout=30)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return list(payload.get("pods") or [])
    return list(payload)


def get_pod(session: requests.Session, pod_id: str) -> tuple[int, dict[str, Any] | None]:
    response = session.get(f"{API}/v2/pods/{pod_id}", timeout=30)
    if response.status_code == 404:
        return 404, None
    response.raise_for_status()
    return response.status_code, response.json()


def list_network_volumes(session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(f"{API}/v2/network-volumes", timeout=30)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return list(payload.get("networkVolumes") or payload.get("volumes") or [])
    return list(payload)


def terminate_pod(session: requests.Session, pod_id: str) -> int:
    response = session.post(
        f"{API}/v2/pods/{pod_id}/action",
        json={"action": "terminate"},
        timeout=30,
    )
    if response.status_code in {200, 204, 404}:
        return response.status_code
    response.raise_for_status()
    return response.status_code


def terminate_named_leftovers(session: requests.Session, prefix: str) -> list[str]:
    terminated: list[str] = []
    for pod in list_pods(session):
        name = str(pod.get("name") or "")
        pod_id = pod.get("id")
        if pod_id and name.startswith(prefix):
            terminate_pod(session, str(pod_id))
            terminated.append(str(pod_id))
    return terminated


def create_pod(
    session: requests.Session,
    *,
    name: str,
    gpu_id: str,
    cloud: str,
    disk: int,
    data_center_ids: list[str] | None,
) -> requests.Response:
    body: dict[str, Any] = {
        "name": name,
        "templateId": TEMPLATE_ID,
        "cloud": cloud,
        "gpu": {"id": gpu_id, "count": 1},
        "disk": disk,
        "ports": ["5001/http", "5001/tcp"],
        "env": {"DOCLING_SERVE_ENABLE_UI": "1"},
    }
    if data_center_ids:
        body["dataCenterIds"] = data_center_ids
    return session.post(f"{API}/v2/pods", json=body, timeout=60)


def wait_until(
    predicate,
    *,
    timeout_s: float,
    interval_s: float,
    label: str,
) -> tuple[bool, float]:
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        if predicate():
            return True, elapsed
        if elapsed >= timeout_s:
            return False, elapsed
        print(f"waiting {label} t={elapsed:.1f}s", flush=True)
        time.sleep(interval_s)


def probe_ready(base_url: str, timeout_s: float = 8.0) -> tuple[bool, str, int | None]:
    """A RunPod proxy 404 means the container is not listening yet. Ignore it."""
    client = requests.Session()
    client.headers["User-Agent"] = USER_AGENT
    last = "no probe"
    for path in READY_PATHS:
        try:
            response = client.get(f"{base_url}{path}", timeout=timeout_s, allow_redirects=True)
        except requests.RequestException as exc:
            last = f"{path} {type(exc).__name__}"
            continue
        last = f"{path} {response.status_code}"
        if 200 <= response.status_code < 400:
            return True, last, response.status_code
    return False, last, None


def linearized_page_count(pdf: bytes) -> int | None:
    match = re.search(rb"/N\s+(\d+)", pdf[:2048])
    if not match:
        return None
    return int(match.group(1))


def load_input_document(path: Path | None) -> tuple[str, bytes, dict[str, Any]]:
    if path is None:
        return (
            "smoke.pdf",
            MINIMAL_PDF,
            {
                "source": "builtin",
                "bytes": len(MINIMAL_PDF),
                "pages_hint": 1,
            },
        )
    data = path.read_bytes()
    return (
        path.name,
        data,
        {
            "source": str(path),
            "bytes": len(data),
            "pages_hint": linearized_page_count(data),
        },
    )


QUALITY_CONVERT_OPTIONS = {
    "to_formats": ["json", "md", "html"],
    "do_ocr": True,
    "table_mode": "accurate",
    "do_table_structure": True,
    "do_pdf_heading_hierarchy": True,
    "do_chart_extraction": True,
    "do_picture_classification": True,
    "image_export_mode": "placeholder",
    "include_images": False,
    "include_page_images": False,
}


def build_convert_options(args: argparse.Namespace) -> dict[str, Any]:
    if args.quality:
        options = dict(QUALITY_CONVERT_OPTIONS)
    else:
        options = {
            "to_formats": ["md"],
            "do_ocr": bool(args.input) if args.do_ocr is None else args.do_ocr,
            "table_mode": args.table_mode or "fast",
        }
    if args.to_formats:
        options["to_formats"] = list(args.to_formats)
    if args.do_ocr is not None:
        options["do_ocr"] = args.do_ocr
    if args.table_mode:
        options["table_mode"] = args.table_mode
    options["document_timeout"] = args.convert_timeout
    return options


def write_convert_artifacts(
    *,
    markdown: str,
    html: str,
    json_document: dict[str, Any] | None,
    markdown_output: str,
    html_output: str,
    json_output: str,
) -> dict[str, Any]:
    written: dict[str, Any] = {}
    if markdown:
        path = Path(markdown_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        written["markdown_path"] = str(path)
        print(f"wrote markdown {path} chars={len(markdown)}", flush=True)
    if html:
        path = Path(html_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        written["html_path"] = str(path)
        print(f"wrote html {path} chars={len(html)}", flush=True)
    if json_document:
        path = Path(json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(json_document, indent=2) + "\n", encoding="utf-8")
        summary = summarize_docling_graph(json_document)
        summary_path = path.with_name(path.stem + ".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        written["json_path"] = str(path)
        written["json_summary_path"] = str(summary_path)
        written["json_nodes"] = summary
        print(
            f"wrote json {path} pages={summary['pages']} "
            f"texts={summary['texts']} tables={summary['tables']} "
            f"pictures={summary['pictures']}",
            flush=True,
        )
    return written


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


def summarize_docling_graph(document: dict[str, Any]) -> dict[str, Any]:
    tables = document.get("tables") or []
    pictures = document.get("pictures") or []
    texts = document.get("texts") or []
    groups = document.get("groups") or []
    pages = document.get("pages") or {}
    table_shapes = []
    for table in tables:
        data = table.get("data") or {}
        grid = data.get("grid") or []
        table_shapes.append(
            {
                "rows": len(grid),
                "cols": len(grid[0]) if grid else int(data.get("num_cols") or 0),
                "label": table.get("label"),
            }
        )
    picture_labels = []
    for picture in pictures:
        classifications = picture.get("classifications") or picture.get("predicted_class")
        picture_labels.append(
            {
                "label": picture.get("label"),
                "classifications": classifications,
            }
        )
    return {
        "schema_name": document.get("schema_name"),
        "name": document.get("name"),
        "pages": len(pages) if isinstance(pages, dict) else 0,
        "texts": len(texts),
        "tables": len(tables),
        "table_shapes": table_shapes,
        "pictures": len(pictures),
        "picture_labels": picture_labels[:20],
        "groups": len(groups),
        "has_body": bool(document.get("body")),
    }


def convert_pdf(
    base_url: str,
    pdf: bytes,
    timeout_s: float,
    *,
    filename: str = "smoke.pdf",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    convert_options = options or {
        "to_formats": ["md"],
        "do_ocr": False,
        "table_mode": "fast",
    }
    started = time.monotonic()
    response = requests.post(
        f"{base_url}/v1/convert/file",
        files={"files": (filename, pdf, "application/pdf")},
        data=convert_form_fields(convert_options),
        headers={"User-Agent": USER_AGENT, "accept": "application/json"},
        timeout=timeout_s,
    )
    elapsed = time.monotonic() - started
    payload = _json_or_text(response)
    markdown = ""
    html = ""
    json_document = None
    errors = None
    if isinstance(payload, dict):
        document = payload.get("document") or {}
        markdown = str(document.get("md_content") or document.get("text_content") or "")
        html = str(document.get("html_content") or "")
        json_document = parse_json_content(document.get("json_content"))
        errors = payload.get("errors")
    return {
        "http_status": response.status_code,
        "seconds": round(elapsed, 3),
        "markdown_chars": len(markdown),
        "html_chars": len(html),
        "json_nodes": summarize_docling_graph(json_document) if json_document else None,
        "markdown_preview": markdown[:160],
        "markdown": markdown,
        "html": html,
        "json_document": json_document,
        "errors": errors,
        "ok": response.status_code == 200 and bool(json_document or markdown),
    }


def estimated_usd(price_per_hour: float | None, seconds: float) -> float | None:
    if price_per_hour is None:
        return None
    return round(price_per_hour * (seconds / 3600.0), 4)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup(signum=None, frame=None) -> None:
    del frame
    pod_id = _active_pod_id
    session = _session
    if pod_id and session is not None:
        print(f"cleanup terminate {pod_id} signal={signum}", flush=True)
        try:
            terminate_pod(session, pod_id)
        except Exception as exc:
            print(f"cleanup failed: {type(exc).__name__}", flush=True)
    if signum is not None:
        sys.exit(128 + int(signum))


def place_pod(
    session: requests.Session,
    *,
    name: str,
    candidates: list[dict[str, Any]],
    cloud: str,
    disk: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        placements = [candidate["data_center_ids"] or None, None]
        seen: set[tuple[str, ...]] = set()
        for data_centers in placements:
            key = tuple(data_centers or ())
            if key in seen:
                continue
            seen.add(key)
            response = create_pod(
                session,
                name=name,
                gpu_id=candidate["id"],
                cloud=cloud,
                disk=disk,
                data_center_ids=data_centers,
            )
            detail = None
            if response.status_code >= 400:
                body = _json_or_text(response)
                if isinstance(body, dict):
                    detail = body.get("detail") or body.get("error") or body.get("message")
                else:
                    detail = str(body)[:200]
            attempts.append(
                {
                    "gpu_id": candidate["id"],
                    "price": candidate["price"],
                    "data_center_ids": data_centers,
                    "http_status": response.status_code,
                    "detail": detail,
                }
            )
            print(
                f"create {candidate['id']} ${candidate['price']}/h "
                f"dc={data_centers or 'any'} -> {response.status_code}",
                flush=True,
            )
            if response.status_code in {429} or response.status_code >= 500:
                time.sleep(3)
                continue
            if response.status_code == 201:
                return response.json(), candidate, attempts
    error = RuntimeError(f"no community GPU accepted a create after {len(attempts)} tries")
    error.attempts = attempts
    raise error


def run_kpi(args: argparse.Namespace) -> dict[str, Any]:
    global _active_pod_id, _session

    api_key = load_api_key(Path(args.env_file))
    session = api_session(api_key)
    _session = session
    result: dict[str, Any] = {
        "started_at": utc_now(),
        "template_id": TEMPLATE_ID,
        "cloud": args.cloud,
        "disk_gb": args.disk,
        "attempts": [],
        "timings_s": {},
        "convert": [],
        "leftover_pods_before": [],
        "leftover_pods_after": [],
        "network_volumes_after": [],
        "ok": False,
    }
    filename, pdf, input_meta = load_input_document(
        Path(args.input) if args.input else None
    )
    convert_options = build_convert_options(args)
    result["input"] = {
        **input_meta,
        "filename": filename,
        "convert_options": convert_options,
    }
    stem = Path(args.input).with_suffix("") if args.input else Path("/opt/cursor/artifacts/smoke")
    markdown_output = args.markdown_output or (str(stem) + ".md")
    json_output = args.json_output or (str(stem) + ".docling.json")
    html_output = args.html_output or (str(stem) + ".html")
    result["markdown_output"] = markdown_output
    result["json_output"] = json_output
    result["html_output"] = html_output

    leftovers = terminate_named_leftovers(session, POD_NAME_PREFIX)
    result["leftover_pods_before"] = leftovers
    if leftovers:
        print(f"terminated leftover pods {leftovers}", flush=True)
        time.sleep(2)

    catalog = session.get(
        f"{API}/v2/catalog/gpus",
        params={"include": "AVAILABILITY", "product": "POD"},
        timeout=60,
    )
    catalog.raise_for_status()
    candidates = rank_gpu_candidates(catalog.json().get("gpus") or [], cloud=args.cloud)
    result["candidates"] = candidates[:12]
    if not candidates:
        raise KpiFailed("catalog had no usable community GPUs", result)
    print(
        "gpu queue "
        + ", ".join(f"{item['id']} ${item['price']}" for item in candidates[:8]),
        flush=True,
    )

    name = f"{POD_NAME_PREFIX}-{int(time.time())}"
    create_started = time.monotonic()
    try:
        pod, chosen, attempts = place_pod(
            session,
            name=name,
            candidates=candidates,
            cloud=args.cloud,
            disk=args.disk,
        )
    except RuntimeError as exc:
        result["attempts"] = getattr(exc, "attempts", [])
        raise KpiFailed(str(exc), result) from exc
    result["attempts"] = attempts
    result["timings_s"]["create_accepted"] = round(time.monotonic() - create_started, 3)
    pod_id = str(pod["id"])
    _active_pod_id = pod_id
    result["pod_id"] = pod_id
    result["gpu"] = {
        "id": chosen["id"],
        "memory_gb": chosen["memory"],
        "price_per_hour": chosen["price"],
        "availability": chosen["availability"],
    }
    print(f"placed {pod_id} on {chosen['id']}", flush=True)

    running: dict[str, Any] = {}

    def _is_running() -> bool:
        nonlocal running
        status_code, current = get_pod(session, pod_id)
        if current is None:
            return False
        running = current
        status = str(current.get("status") or "")
        print(f"pod status={status} code={status_code}", flush=True)
        if status in {"FAILED", "TERMINATED", "DEAD"}:
            raise KpiFailed(f"pod entered {status}", result)
        return status == "RUNNING"

    ok_running, running_s = wait_until(
        _is_running,
        timeout_s=args.bringup_timeout,
        interval_s=5,
        label="RUNNING",
    )
    result["timings_s"]["status_running"] = round(running_s, 3)
    if not ok_running:
        raise KpiFailed("pod did not reach RUNNING", result)
    result["data_center_id"] = running.get("dataCenterId")
    result["pod_cost"] = running.get("cost")
    result["ports"] = (running.get("runtime") or {}).get("ports")

    ready_url = None
    ready_detail = None

    def _is_http_ready() -> bool:
        nonlocal ready_url, ready_detail, running
        _, current = get_pod(session, pod_id)
        if current:
            running = current
        for url in collect_base_urls(running):
            ok, detail, _status = probe_ready(url)
            ready_detail = f"{url} {detail}"
            print(f"probe {ready_detail}", flush=True)
            if ok:
                ready_url = url
                return True
        return False

    ok_ready, ready_s = wait_until(
        _is_http_ready,
        timeout_s=args.ready_timeout,
        interval_s=8,
        label="HTTP ready",
    )
    result["timings_s"]["http_ready_after_running"] = round(ready_s, 3)
    result["timings_s"]["bring_up"] = round(time.monotonic() - create_started, 3)
    result["ready_url_kind"] = (
        "proxy" if ready_url and "proxy.runpod.net" in ready_url else "direct"
    )
    result["ready_detail"] = ready_detail
    if not ok_ready or not ready_url:
        raise KpiFailed(f"Docling Serve did not become reachable ({ready_detail})", result)

    labels = ("cold",) if args.skip_warm else ("cold", "warm")
    for label in labels:
        convert = convert_pdf(
            ready_url,
            pdf,
            args.convert_timeout,
            filename=filename,
            options=convert_options,
        )
        convert["label"] = label
        markdown = convert.pop("markdown", "")
        html = convert.pop("html", "")
        json_document = convert.pop("json_document", None)
        if label == "cold":
            written = write_convert_artifacts(
                markdown=markdown,
                html=html,
                json_document=json_document,
                markdown_output=markdown_output,
                html_output=html_output,
                json_output=json_output,
            )
            convert.update(written)
        result["convert"].append(convert)
        print(
            f"convert {label} {convert['http_status']} "
            f"{convert['seconds']}s md={convert['markdown_chars']} "
            f"json={bool(convert.get('json_nodes'))}",
            flush=True,
        )
        if not convert["ok"]:
            raise KpiFailed(f"{label} convert failed HTTP {convert['http_status']}", result)

    result["timings_s"]["docling_cold"] = result["convert"][0]["seconds"]
    if len(result["convert"]) > 1:
        result["timings_s"]["docling_warm"] = result["convert"][1]["seconds"]

    terminate_started = time.monotonic()
    terminate_status = terminate_pod(session, pod_id)
    result["timings_s"]["terminate_accepted"] = round(time.monotonic() - terminate_started, 3)
    result["terminate_http_status"] = terminate_status
    _active_pod_id = None

    def _is_gone() -> bool:
        status_code, current = get_pod(session, pod_id)
        if status_code == 404 or current is None:
            return True
        status = str(current.get("status") or "")
        print(f"teardown status={status}", flush=True)
        return status in {"TERMINATED", "DEAD"}

    ok_gone, gone_s = wait_until(
        _is_gone,
        timeout_s=args.teardown_timeout,
        interval_s=3,
        label="terminated",
    )
    result["timings_s"]["teardown"] = round(gone_s, 3)
    result["timings_s"]["billed_window"] = round(time.monotonic() - create_started, 3)
    if not ok_gone:
        raise KpiFailed("pod still present after terminate", result)

    remaining = [
        {"id": pod.get("id"), "name": pod.get("name"), "status": pod.get("status")}
        for pod in list_pods(session)
    ]
    volumes = []
    try:
        volumes = [
            {"id": item.get("id"), "name": item.get("name"), "size": item.get("size")}
            for item in list_network_volumes(session)
        ]
    except requests.HTTPError as exc:
        volumes = [{"error": str(exc.response.status_code)}]
    result["leftover_pods_after"] = remaining
    result["network_volumes_after"] = volumes
    result["estimated_usd"] = estimated_usd(
        chosen["price"], result["timings_s"]["billed_window"]
    )
    result["ok"] = True
    result["finished_at"] = utc_now()
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--cloud", default="COMMUNITY", choices=("COMMUNITY", "SECURE"))
    parser.add_argument("--disk", type=int, default=DEFAULT_DISK_GB)
    parser.add_argument("--bringup-timeout", type=float, default=1200)
    parser.add_argument("--ready-timeout", type=float, default=900)
    parser.add_argument("--convert-timeout", type=float, default=600)
    parser.add_argument("--teardown-timeout", type=float, default=300)
    parser.add_argument("--input", help="PDF to convert. Default is the built-in one-page smoke file.")
    parser.add_argument(
        "--markdown-output",
        help="Where to write the cold-convert markdown. Defaults to <input>.md.",
    )
    parser.add_argument("--json-output", help="Where to write the Docling JSON graph.")
    parser.add_argument("--html-output", help="Where to write HTML.")
    parser.add_argument(
        "--do-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="OCR on convert. Default on when --input is set, off for the smoke PDF.",
    )
    parser.add_argument("--table-mode", default=None, choices=("fast", "accurate"))
    parser.add_argument(
        "--to-format",
        action="append",
        dest="to_formats",
        choices=("md", "json", "html", "text", "doctags"),
        help="Repeatable. Default is md, or json+md+html with --quality.",
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="Accurate tables, heading hierarchy, chart extraction, JSON graph.",
    )
    parser.add_argument(
        "--skip-warm",
        action="store_true",
        help="Convert once. Skip the second warm pass.",
    )
    parser.add_argument(
        "--output",
        default="/opt/cursor/artifacts/runpod-docling-kpi.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"ok": False}
    try:
        result = run_kpi(args)
        return 0
    except KpiFailed as exc:
        result = exc.result
        result["error"] = str(exc)
        result["ok"] = False
        result["finished_at"] = utc_now()
        print(f"kpi failed: {exc}", flush=True)
        return 1
    except Exception as exc:
        result.setdefault("error", f"{type(exc).__name__}: {exc}")
        result["ok"] = False
        result["finished_at"] = utc_now()
        print(f"kpi failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        if _active_pod_id and _session is not None:
            print(f"final terminate {_active_pod_id}", flush=True)
            try:
                terminate_pod(_session, _active_pod_id)
            except Exception as exc:
                print(f"final terminate failed: {type(exc).__name__}", flush=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {output_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

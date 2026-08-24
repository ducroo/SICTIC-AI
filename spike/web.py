from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

from aiohttp import web

from lib.logger import get_logger
from spike.runtime import (
    DemoResult,
    SpikeStatus,
    parse_skill_call,
    run_demo,
    run_skill,
    spike_status,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class DemoRequest:
    filename: str
    payload: bytes
    query: str


def _present(flag: bool) -> str:
    return "yes" if flag else "no"


def render_page(
    *,
    status: SpikeStatus,
    result: DemoResult | None = None,
    error: str = "",
    query: str = "",
    markdown: str = "",
) -> str:
    skills = "".join(
        f"<li><code>{escape(skill.name)}</code></li>" for skill in status.skills
    )
    error_html = f"<p class=\"error\">{escape(error)}</p>" if error else ""
    hits_html = ""
    if result is not None:
        if result.hits:
            items = []
            for hit in result.hits:
                items.append(
                    "<article class=\"hit\">"
                    f"<p><strong>{escape(hit.document_name)}</strong>"
                    f" · page {escape(hit.page_number)}</p>"
                    f"<pre>{escape(hit.text)}</pre>"
                    "</article>"
                )
            hits_html = (
                f"<h2>Hits in <code>{escape(result.dataset_name)}</code></h2>"
                + "".join(items)
            )
        else:
            hits_html = (
                f"<h2>Hits in <code>{escape(result.dataset_name)}</code></h2>"
                "<p>No hits.</p>"
            )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SICTIC spike</title>
  <style>
    body {{ font-family: sans-serif; max-width: 48rem; margin: 1.5rem auto; padding: 0 1rem; }}
    label, textarea, input[type=text] {{ display: block; width: 100%; }}
    textarea {{ min-height: 10rem; }}
    .hit {{ border-top: 1px solid #ccc; padding: 0.75rem 0; }}
    pre {{ white-space: pre-wrap; }}
    .error {{ color: #a40000; }}
  </style>
</head>
<body>
  <h1>SICTIC spike</h1>
  <dl>
    <dt>Parser</dt><dd><code>{escape(status.parser)}</code></dd>
    <dt>Store</dt><dd><code>{escape(status.store)}</code></dd>
    <dt>LlamaCloud key</dt><dd>{_present(status.llama_cloud_key)}</dd>
    <dt>Firebase credentials</dt><dd>{_present(status.firebase_credentials)}</dd>
    <dt>Embedding model</dt><dd><code>{escape(status.embedding_model)}</code></dd>
  </dl>
  <h2>Skills</h2>
  <ul>{skills}</ul>
  {error_html}
  <form method="post" action="/demo" enctype="multipart/form-data">
    <label for="query">Query</label>
    <input id="query" name="query" type="text" value="{escape(query, quote=True)}">
    <label for="markdown">Markdown</label>
    <textarea id="markdown" name="markdown">{escape(markdown)}</textarea>
    <label for="file">File</label>
    <input id="file" name="file" type="file">
    <button type="submit">Search</button>
  </form>
  {hits_html}
</body>
</html>
"""


def parse_demo_request(post) -> DemoRequest:
    query = str(post.get("query") or "").strip()
    markdown = str(post.get("markdown") or "")
    upload = post.get("file")
    filename = "note.md"
    payload = b""
    file_obj = getattr(upload, "file", None)
    if file_obj is not None:
        data = file_obj.read()
        if data:
            name = Path(getattr(upload, "filename", "") or "").name
            filename = name or "upload.bin"
            payload = data
    if not payload:
        payload = markdown.encode("utf-8")
        filename = "note.md"
    if not payload.strip() or not query:
        raise ValueError("Query and markdown (or a file) are required.")
    return DemoRequest(filename=filename, payload=payload, query=query)


def parse_json_demo(body: object) -> DemoRequest:
    if not isinstance(body, dict):
        raise ValueError("JSON object required.")
    query = str(body.get("query") or "").strip()
    markdown = str(body.get("markdown") or "")
    if not markdown.strip() or not query:
        raise ValueError("Query and markdown are required.")
    return DemoRequest(filename="note.md", payload=markdown.encode("utf-8"), query=query)


def parse_json_skill(body: object):
    if not isinstance(body, dict):
        raise ValueError("JSON object required.")
    return parse_skill_call(
        skill=str(body.get("skill") or ""),
        args=str(body.get("args") or ""),
    )


def demo_result_payload(result: DemoResult) -> dict:
    return {
        "dataset_name": result.dataset_name,
        "hits": [asdict(hit) for hit in result.hits],
    }


def _health_payload(status: SpikeStatus) -> dict:
    ok = bool(status.parser) and bool(status.store)
    return {
        "ok": ok,
        "parser": status.parser,
        "store": status.store,
        "llama_cloud_key": status.llama_cloud_key,
        "firebase_credentials": status.firebase_credentials,
    }


async def handle_index(_request: web.Request) -> web.Response:
    return web.Response(
        text=render_page(status=spike_status()),
        content_type="text/html",
    )


async def handle_demo(request: web.Request) -> web.Response:
    status = spike_status()
    try:
        demo = parse_demo_request(await request.post())
    except ValueError as error:
        return web.Response(
            text=render_page(status=status, error=str(error)),
            content_type="text/html",
            status=400,
        )
    try:
        result = await run_demo(
            filename=demo.filename,
            payload=demo.payload,
            query=demo.query,
        )
    except Exception as error:
        logger.exception("Demo failed.")
        markdown = (
            demo.payload.decode("utf-8", errors="replace")
            if demo.filename.lower().endswith(".md")
            else ""
        )
        return web.Response(
            text=render_page(
                status=status,
                error=str(error),
                query=demo.query,
                markdown=markdown,
            ),
            content_type="text/html",
            status=500,
        )
    return web.Response(
        text=render_page(status=status, result=result, query=demo.query),
        content_type="text/html",
    )


async def handle_healthz(_request: web.Request) -> web.Response:
    try:
        status = spike_status()
    except Exception:
        logger.exception("Health status failed.")
        return web.json_response(
            {
                "ok": False,
                "parser": "",
                "store": "",
                "llama_cloud_key": False,
                "firebase_credentials": False,
            }
        )
    return web.json_response(_health_payload(status))


async def handle_api_status(_request: web.Request) -> web.Response:
    return web.json_response(asdict(spike_status()))


async def handle_api_demo(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        demo = parse_json_demo(body)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception:
        return web.json_response({"error": "JSON object required."}, status=400)
    try:
        result = await run_demo(
            filename=demo.filename,
            payload=demo.payload,
            query=demo.query,
        )
    except Exception as error:
        logger.exception("Demo failed.")
        return web.json_response({"error": str(error)}, status=500)
    return web.json_response(demo_result_payload(result))


async def handle_api_skill(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        call = parse_json_skill(body)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception:
        return web.json_response({"error": "JSON object required."}, status=400)
    try:
        result = await run_skill(call)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        logger.exception("Skill failed.")
        return web.json_response({"error": str(error)}, status=500)
    return web.json_response(asdict(result))


ROUTES = (
    web.get("/", handle_index),
    web.post("/demo", handle_demo),
    web.get("/healthz", handle_healthz),
    web.get("/api/status", handle_api_status),
    web.post("/api/demo", handle_api_demo),
    web.post("/api/skill", handle_api_skill),
)


def create_app() -> web.Application:
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.add_routes(ROUTES)
    return app


def main() -> None:
    port = int(os.environ.get("PORT") or "8080")
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

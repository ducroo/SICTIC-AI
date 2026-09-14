"""In-process Docling Serve stand-in for tests and local UI checks."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from aiohttp import web

from lib.infrastructure.document_conversion.graph_markdown import graph_to_markdown


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

SAMPLE_GRAPH: dict[str, Any] = {
    "schema_name": "DoclingDocument",
    "name": "acme-robotics.pdf",
    "body": {
        "children": [
            {"$ref": "#/texts/0"},
            {"$ref": "#/groups/0"},
            {"$ref": "#/tables/0"},
        ]
    },
    "texts": [
        {
            "label": "section_header",
            "level": 1,
            "text": "Acme Robotics",
            "prov": [{"page_no": 1}],
        },
        {
            "label": "text",
            "text": "14.4%",
            "prov": [{"page_no": 1}],
        },
        {
            "label": "text",
            "text": "CET1 capital ratio",
            "prov": [{"page_no": 1}],
        },
        {
            "label": "page_header",
            "text": "Media Relations",
            "prov": [{"page_no": 1}],
        },
    ],
    "groups": [
        {
            "label": "key_value_area",
            "children": [{"$ref": "#/texts/1"}, {"$ref": "#/texts/2"}],
            "prov": [{"page_no": 1}],
        }
    ],
    "tables": [
        {
            "data": {
                "grid": [
                    [{"text": "USD m"}, {"text": "GWM"}],
                    [{"text": "Revenue"}, {"text": "7,112"}],
                ]
            },
            "prov": [{"page_no": 1}],
        }
    ],
    "pages": {"1": {}},
}


def sample_markdown() -> str:
    return graph_to_markdown(SAMPLE_GRAPH)


def create_app(
    *,
    graph: dict[str, Any] | None = None,
    markdown: str | None = None,
) -> web.Application:
    state = {
        "graph": graph if graph is not None else SAMPLE_GRAPH,
        "markdown": markdown if markdown is not None else sample_markdown(),
        "tasks": {},
        "uploads": [],
    }
    app = web.Application()
    app["state"] = state
    app.add_routes(
        [
            web.get("/docs", _handle_docs),
            web.get("/health", _handle_health),
            web.post("/v1/convert/file/async", _handle_submit),
            web.get("/v1/status/poll/{task_id}", _handle_poll),
            web.get("/v1/result/{task_id}", _handle_result),
        ]
    )
    return app


async def _handle_docs(_request: web.Request) -> web.Response:
    return web.Response(text="ok", content_type="text/html")


async def _handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _handle_submit(request: web.Request) -> web.Response:
    post = await request.post()
    upload = post.get("files")
    filename = getattr(upload, "filename", "") or ""
    payload = b""
    file_obj = getattr(upload, "file", None)
    if file_obj is not None:
        payload = file_obj.read()
    request.app["state"]["uploads"].append(
        {"filename": filename, "bytes": len(payload)}
    )
    task_id = uuid4().hex
    request.app["state"]["tasks"][task_id] = "success"
    return web.json_response({"task_id": task_id, "task_status": "pending"})


async def _handle_poll(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    status = request.app["state"]["tasks"].get(task_id, "failure")
    return web.json_response({"task_id": task_id, "task_status": status})


async def _handle_result(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    status = request.app["state"]["tasks"].get(task_id)
    if status != "success":
        return web.json_response({"detail": "Task result not found"}, status=404)
    state = request.app["state"]
    return web.json_response(
        {
            "document": {
                "md_content": state["markdown"],
                "json_content": state["graph"],
            }
        }
    )


def main() -> None:
    port = int(os.environ.get("PORT") or "5001")
    web.run_app(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

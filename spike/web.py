from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

from aiohttp import web

from lib.infrastructure.logging import get_logger
from spike.runtime import (
    SpikeStatus,
    check_pitch_deck_upload,
    parse_skill_call,
    review_pitch_deck_upload,
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

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "sictic-logo.svg": "image/svg+xml",
    "safe-swiss-cloud-logo.svg": "image/svg+xml",
    "review.js": "text/javascript",
}

REVIEW_STEPS = (
    ("receive", "Receive the deck"),
    ("extract", "Extract the text"),
    ("review", "Review the deck"),
    ("report", "Prepare the report"),
)
WORKING_MESSAGE = "We're working on your deck."

_STATUS_CLASS = {
    "Fine": "status-fine",
    "Sufficient": "status-sufficient",
    "Borderline": "status-borderline",
    "Critical": "status-critical",
    "Not Found": "status-missing",
}


def _inline(text: str) -> str:
    escaped = escape(text).replace(r"\|", "|")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return ""
    header, _separator, body = rows[0], rows[1], rows[2:]
    head = "".join(f"<th>{_inline(cell)}</th>" for cell in header)
    body_html = []
    for cells in body:
        rendered = []
        for index, cell in enumerate(cells):
            status_class = _STATUS_CLASS.get(cell, "")
            class_attr = f' class="{status_class}"' if status_class else ""
            tag = "th" if index == 0 else "td"
            rendered.append(f"<{tag}{class_attr}>{_inline(cell)}</{tag}>")
        body_html.append("<tr>" + "".join(rendered) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body_html)
        + "</tbody></table></div>"
    )


def render_report(markdown: str) -> str:
    """Render the pitch-deck report. The report is headings, lists, and one table."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    table: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{_inline(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    def flush_table() -> None:
        if table:
            blocks.append(_table(table))
            table.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            flush_paragraph()
            flush_list()
            table.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            list_items.append(bullet.group(1))
            continue
        flush_list()
        paragraph.append(line.strip())
    flush_paragraph()
    flush_list()
    flush_table()
    return "\n".join(blocks)


def render_page(*, error: str = "", report: str = "", filename: str = "") -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    report_html = ""
    if report:
        label = escape(filename) if filename else "your deck"
        report_html = (
            f'<section class="report"><h2>Review of {label}</h2>'
            f"{render_report(report)}</section>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Check your pitch deck · SICTIC</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;600&family=Montserrat:wght@600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --red: #bc2132;
      --ink: #212529;
      --muted: #607382;
      --line: #d2d6dc;
      --paper: #f6f6f6;
      --card: #fff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Figtree, Helvetica, Arial, sans-serif;
      color: var(--ink);
      background: var(--paper);
      line-height: 1.5;
    }}
    a {{ color: var(--red); }}
    header {{
      background: var(--card);
      border-bottom: 4px solid var(--red);
    }}
    .bar {{
      max-width: 52rem;
      margin: 0 auto;
      padding: 0.9rem 1.25rem;
      display: flex;
      align-items: center;
    }}
    .brand img {{ height: 36px; width: auto; display: block; }}
    main {{
      max-width: 52rem;
      margin: 0 auto;
      padding: 2rem 1.25rem 3rem;
    }}
    h1, h2, h3 {{
      font-family: Montserrat, Figtree, Helvetica, Arial, sans-serif;
      line-height: 1.2;
    }}
    h1 {{ font-size: 2rem; margin: 0 0 0.75rem; }}
    .lead {{ font-size: 1.05rem; max-width: 40rem; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      padding: 1.25rem;
      margin-top: 1.5rem;
    }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.35rem; }}
    input[type=file] {{ display: block; width: 100%; }}
    .hint {{ color: var(--muted); margin: 0.4rem 0 1rem; }}
    button {{
      background: var(--red);
      color: #fff;
      border: 0;
      font: 600 1rem/1 Figtree, Helvetica, Arial, sans-serif;
      padding: 0.85rem 1.2rem;
      cursor: pointer;
    }}
    button:hover {{ background: #a41c2b; }}
    button:disabled {{
      background: #607382;
      cursor: not-allowed;
    }}
    .working {{
      margin-top: 1.25rem;
      padding-top: 1rem;
      border-top: 1px solid var(--line);
    }}
    .steps {{
      list-style: none;
      margin: 0.75rem 0 0;
      padding: 0;
    }}
    .steps li {{
      padding: 0.35rem 0 0.35rem 0.8rem;
      border-left: 3px solid var(--line);
      color: var(--muted);
    }}
    .steps li.current {{
      border-left-color: var(--red);
      color: var(--ink);
      font-weight: 600;
    }}
    .steps li.done {{
      border-left-color: #0b6e4f;
      color: #0b6e4f;
    }}
    .elapsed {{ color: var(--muted); margin: 0.4rem 0 0; }}
    .error {{ color: var(--red); font-weight: 600; }}
    .report {{ margin-top: 2rem; }}
    .report h2 {{ margin-top: 0; }}
    .table-wrap {{ overflow-x: auto; background: var(--card); border: 1px solid var(--line); }}
    table {{ border-collapse: collapse; width: 100%; min-width: 42rem; font-size: 0.92rem; }}
    th, td {{ text-align: left; vertical-align: top; padding: 0.55rem 0.7rem; border-bottom: 1px solid var(--line); }}
    thead th {{ background: #f6f6f6; }}
    .status-fine {{ color: #0b6e4f; font-weight: 600; }}
    .status-sufficient {{ color: #0070ad; font-weight: 600; }}
    .status-borderline {{ color: #f17e00; font-weight: 600; }}
    .status-critical {{ color: var(--red); font-weight: 600; }}
    .status-missing {{ color: var(--muted); font-weight: 600; }}
    footer {{
      background: var(--card);
      border-top: 1px solid var(--line);
    }}
    .sponsor {{
      max-width: 52rem;
      margin: 0 auto;
      padding: 1.25rem;
      display: flex;
      align-items: center;
      gap: 0.9rem;
      color: var(--muted);
    }}
    .sponsor-logo {{
      background: #4b5563;
      padding: 0.45rem 0.7rem;
      line-height: 0;
    }}
    .sponsor-logo img {{ height: 32px; width: auto; display: block; }}
    @media (max-width: 640px) {{
      h1 {{ font-size: 1.6rem; }}
      button {{ width: 100%; }}
      .sponsor {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <a class="brand" href="https://www.sictic.ch/">
        <img src="/static/sictic-logo.svg" alt="SICTIC">
      </a>
    </div>
  </header>
  <main>
    <h1>Check your pitch deck</h1>
    <p class="lead">Upload the deck you would send to SICTIC. The review reads it against the jury criteria and the investment criteria published for startups that want to pitch at an Investor Day. This is a document check. It is not a jury decision, and it does not submit an application.</p>
    <p><a href="https://www.sictic.ch/startups/">Read the criteria on sictic.ch</a></p>
    <form class="card" method="post" action="/review" enctype="multipart/form-data">
      {error_html}
      <label for="deck">Pitch deck</label>
      <input id="deck" name="deck" type="file" accept=".pdf,.ppt,.pptx,application/pdf,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation" required>
      <p class="hint">PDF or PowerPoint. The review uses the text in the file. A long deck can take a few minutes.</p>
      <button type="submit">Review this deck</button>
      <div id="working" class="working" hidden>
        <p id="working-message">{WORKING_MESSAGE}</p>
        <p id="elapsed" class="elapsed">Elapsed 0:00</p>
        <ol class="steps">
          <li data-step="receive">1. Receive the deck</li>
          <li data-step="extract">2. Extract the text</li>
          <li data-step="review">3. Review the deck</li>
          <li data-step="report">4. Prepare the report</li>
        </ol>
      </div>
    </form>
    <div id="report">{report_html}</div>
  </main>
  <footer>
    <div class="sponsor">
      <span>Hosting sponsored by Safe Swiss Cloud</span>
      <a class="sponsor-logo" href="https://safeswisscloud.com/">
        <img src="/static/safe-swiss-cloud-logo.svg" alt="Safe Swiss Cloud">
      </a>
    </div>
  </footer>
  <script src="/static/review.js"></script>
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


def demo_result_payload(result) -> dict:
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
    return web.Response(text=render_page(), content_type="text/html")


async def handle_static(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    content_type = STATIC_FILES.get(name)
    path = STATIC_DIR / name
    if content_type is None or not path.is_file():
        raise web.HTTPNotFound()
    return web.Response(body=path.read_bytes(), content_type=content_type)


class ReviewJob:
    def __init__(self, job_id: str, filename: str) -> None:
        self.id = job_id
        self.filename = filename
        self.step = "receive"
        self.started = time.monotonic()
        self.done = False
        self.error = ""
        self.report = ""
        self.status = 200


_jobs: dict[str, ReviewJob] = {}


def _job_status(job: ReviewJob) -> dict:
    keys = [key for key, _label in REVIEW_STEPS]
    if job.done and not job.error:
        index = len(keys)
    else:
        index = keys.index(job.step) if job.step in keys else 0
    steps = []
    for position, (key, label) in enumerate(REVIEW_STEPS):
        if job.done and not job.error:
            state = "done"
        elif position < index:
            state = "done"
        elif position == index:
            state = "current"
        else:
            state = "waiting"
        steps.append({"id": key, "label": label, "state": state})
    body = {
        "job_id": job.id,
        "message": WORKING_MESSAGE,
        "step": "report" if job.done and not job.error else job.step,
        "steps": steps,
        "elapsed_seconds": max(0, int(time.monotonic() - job.started)),
        "done": job.done,
        "error": job.error,
    }
    if job.done and not job.error:
        body["report_html"] = (
            f'<section class="report"><h2>Review of {escape(job.filename)}</h2>'
            f"{render_report(job.report)}</section>"
        )
    return body


def _prune_jobs() -> None:
    cutoff = time.monotonic() - 7200
    for key, job in list(_jobs.items()):
        if job.started < cutoff:
            del _jobs[key]


def _upload_file(post) -> tuple[str, bytes]:
    upload = post.get("deck")
    filename = Path(getattr(upload, "filename", "") or "").name
    file_obj = getattr(upload, "file", None)
    payload = file_obj.read() if file_obj is not None else b""
    return filename, payload


async def _finish_job(job: ReviewJob, filename: str, payload: bytes) -> None:
    def on_progress(step: str) -> None:
        job.step = step

    try:
        job.report = await review_pitch_deck_upload(
            filename=filename,
            payload=payload,
            on_progress=on_progress,
        )
        job.step = "report"
        job.done = True
    except ValueError as error:
        job.error = str(error)
        job.status = 400
        job.done = True
    except Exception as error:
        logger.exception("Pitch deck review failed.")
        job.error = str(error)
        job.status = 500
        job.done = True


async def handle_review_start(request: web.Request) -> web.Response:
    filename, payload = _upload_file(await request.post())
    if not filename or not payload:
        return web.json_response(
            {"error": "Choose a PDF or PowerPoint pitch deck."},
            status=400,
        )
    try:
        check_pitch_deck_upload(filename, payload)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    _prune_jobs()
    job = ReviewJob(uuid.uuid4().hex, filename)
    _jobs[job.id] = job
    asyncio.create_task(_finish_job(job, filename, payload))
    return web.json_response(_job_status(job))


async def handle_review_status(request: web.Request) -> web.Response:
    job = _jobs.get(request.match_info["job_id"])
    if job is None:
        return web.json_response({"error": "That review is no longer available."}, status=404)
    return web.json_response(_job_status(job))


async def handle_review(request: web.Request) -> web.Response:
    post = await request.post()
    filename, payload = _upload_file(post)
    if not filename or not payload:
        return web.Response(
            text=render_page(error="Choose a PDF or PowerPoint pitch deck."),
            content_type="text/html",
            status=400,
        )
    try:
        report = await review_pitch_deck_upload(filename=filename, payload=payload)
    except ValueError as error:
        return web.Response(
            text=render_page(error=str(error), filename=filename),
            content_type="text/html",
            status=400,
        )
    except Exception as error:
        logger.exception("Pitch deck review failed.")
        return web.Response(
            text=render_page(error=str(error), filename=filename),
            content_type="text/html",
            status=500,
        )
    return web.Response(
        text=render_page(report=report, filename=filename),
        content_type="text/html",
    )


async def handle_demo(request: web.Request) -> web.Response:
    try:
        demo = parse_demo_request(await request.post())
    except ValueError as error:
        return web.Response(text=str(error), status=400)
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
    web.get("/static/{name}", handle_static),
    web.post("/review", handle_review),
    web.post("/review/start", handle_review_start),
    web.get("/review/status/{job_id}", handle_review_status),
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

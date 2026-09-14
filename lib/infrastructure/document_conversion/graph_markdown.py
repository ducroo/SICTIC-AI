"""Turn a DoclingDocument JSON graph into SICTIC-shaped Markdown.

CPU only. No GPU, no Docling runtime. The graph is the source of truth.
Markdown is a derived view for the existing chunker and skills.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lib.datasets.page_markers import format_page_marker


SKIP_TEXT_LABELS = frozenset({"page_header", "page_footer"})


def load_graph(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def resolve_ref(graph: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    if len(parts) != 2:
        return None
    kind, index = parts[0], parts[1]
    bucket = graph.get(kind)
    if not isinstance(bucket, list):
        return None
    try:
        node = bucket[int(index)]
    except (IndexError, ValueError):
        return None
    return node if isinstance(node, dict) else None


def page_of(node: dict[str, Any] | None) -> int | None:
    if not node:
        return None
    for prov in node.get("prov") or []:
        page = prov.get("page_no")
        if page is not None:
            return int(page)
    return None


def child_refs(node: dict[str, Any] | None) -> list[str]:
    if not node:
        return []
    refs: list[str] = []
    for child in node.get("children") or []:
        if isinstance(child, dict) and child.get("$ref"):
            refs.append(str(child["$ref"]))
    return refs


def table_markdown(table: dict[str, Any]) -> str:
    grid = ((table.get("data") or {}).get("grid")) or []
    if not grid:
        return ""
    rows: list[list[str]] = []
    for raw_row in grid:
        row = []
        for cell in raw_row:
            text = cell.get("text") if isinstance(cell, dict) else str(cell or "")
            row.append(" ".join(str(text or "").split()))
        rows.append(row)
    width = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (width - len(row)))
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def key_value_markdown(graph: dict[str, Any], group: dict[str, Any]) -> str:
    items: list[str] = []
    for ref in child_refs(group):
        node = resolve_ref(graph, ref)
        if not node:
            continue
        if node.get("label") in SKIP_TEXT_LABELS:
            continue
        text = " ".join(str(node.get("text") or "").split())
        if text:
            items.append(text)
    if not items:
        return ""
    pairs = []
    for index in range(0, len(items), 2):
        value = items[index]
        label = items[index + 1] if index + 1 < len(items) else ""
        if label:
            pairs.append(f"| {label} | {value} |")
        else:
            pairs.append(f"| {value} |  |")
    if not pairs:
        return ""
    return "| Metric | Value |\n| --- | --- |\n" + "\n".join(pairs)


def text_markdown(node: dict[str, Any]) -> str:
    label = str(node.get("label") or "")
    if label in SKIP_TEXT_LABELS:
        return ""
    text = " ".join(str(node.get("text") or "").split())
    if not text:
        return ""
    if label == "section_header":
        level = int(node.get("level") or 1)
        hashes = "#" * min(max(level, 1), 6)
        return f"{hashes} {text}"
    if label == "caption":
        return f"*{text}*"
    return text


def picture_markdown(node: dict[str, Any]) -> str:
    page = page_of(node)
    where = f" page {page}" if page else ""
    return f"<!-- figure{where} -->"


def render_node(
    graph: dict[str, Any], ref: str, seen: set[str]
) -> Iterable[tuple[int | None, str]]:
    if ref in seen:
        return
    seen.add(ref)
    node = resolve_ref(graph, ref)
    if not node:
        return
    kind = ref.split("/")[1] if "/" in ref else ""
    page = page_of(node)
    if kind == "texts":
        block = text_markdown(node)
        if block:
            yield page, block
        return
    if kind == "tables":
        block = table_markdown(node)
        if block:
            yield page, block
        return
    if kind == "pictures":
        yield page, picture_markdown(node)
        return
    if kind == "groups":
        if node.get("label") == "key_value_area":
            block = key_value_markdown(graph, node)
            if block:
                yield page, block
            return
        for child in child_refs(node):
            yield from render_node(graph, child, seen)


def graph_to_markdown(graph: dict[str, Any]) -> str:
    seen: set[str] = set()
    blocks: list[tuple[int | None, str]] = []
    for ref in child_refs(graph.get("body") or {}):
        blocks.extend(render_node(graph, ref, seen))
    lines: list[str] = []
    current_page: int | None = None
    for page, block in blocks:
        if page is not None and page != current_page:
            lines.append(format_page_marker(page))
            current_page = page
        lines.append(block)
        lines.append("")
    return "\n".join(lines).strip() + "\n"

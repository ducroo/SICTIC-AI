"""CLI wrapper around the canonical Docling JSON graph renderer."""

from __future__ import annotations

import argparse
from pathlib import Path

from lib.infrastructure.document_conversion.graph_markdown import (
    SKIP_TEXT_LABELS,
    child_refs,
    graph_to_markdown,
    key_value_markdown,
    load_graph,
    page_of,
    picture_markdown,
    render_node,
    resolve_ref,
    table_markdown,
    text_markdown,
)

__all__ = [
    "SKIP_TEXT_LABELS",
    "child_refs",
    "graph_to_markdown",
    "key_value_markdown",
    "load_graph",
    "page_of",
    "picture_markdown",
    "render_node",
    "resolve_ref",
    "table_markdown",
    "text_markdown",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    markdown = graph_to_markdown(load_graph(args.graph))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.output} chars={len(markdown)}", flush=True)
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

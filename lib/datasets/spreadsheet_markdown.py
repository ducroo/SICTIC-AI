"""Shared structure of spreadsheet-derived Markdown.

Kept free of heavy imports so both the Docling adapter and the chunker can
use it without pulling in document conversion dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lib.datasets.markdown_tables import select_header

SPREADSHEET_MARKDOWN_MARKER = "<!-- sictic-spreadsheet: compact-values-v3 -->"
SPREADSHEET_MARKER_RE = re.compile(r"<!--\s*sictic-spreadsheet:[^>]*-->")
SHEET_HEADING_RE = re.compile(r"^##\s+(.*)$")


@dataclass(frozen=True)
class SheetSection:
    """One worksheet: its title, its header row, and its remaining rows."""

    name: str
    header: str
    rows: list[str]


def is_spreadsheet_markdown(text: str) -> bool:
    return bool(SPREADSHEET_MARKER_RE.match(text.lstrip()))


def split_sheets(text: str) -> list[SheetSection]:
    """Split spreadsheet Markdown into per-worksheet sections."""
    body = SPREADSHEET_MARKER_RE.sub("", text, count=1)
    sections: list[SheetSection] = []
    name = ""
    rows: list[str] = []

    def flush() -> None:
        if not rows:
            return
        header_index = select_header(rows)
        header = rows[header_index] if header_index >= 0 else ""
        remaining = [
            row for index, row in enumerate(rows) if index != header_index
        ]
        sections.append(SheetSection(name=name, header=header, rows=remaining))

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = SHEET_HEADING_RE.match(stripped)
        if heading:
            flush()
            name = heading.group(1).strip()
            rows = []
            continue
        rows.append(stripped)

    flush()
    return sections

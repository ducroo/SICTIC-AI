"""Page boundary markers embedded in parsed Markdown."""

from __future__ import annotations

import re

PAGE_MARKER_RE = re.compile(r"<!-- sictic-page:(\d+) -->\s*")
UNKNOWN_PAGE = "n/a"


def format_page_marker(page: int) -> str:
    return f"<!-- sictic-page:{page} -->"


def split_text_by_pages(text: str) -> list[tuple[int | str, str]]:
    """Split parsed Markdown into (page_number, section_text) pairs."""
    if not PAGE_MARKER_RE.search(text):
        stripped = text.strip()
        return [(UNKNOWN_PAGE, stripped)] if stripped else []

    sections: list[tuple[int | str, str]] = []
    current_page: int | str = UNKNOWN_PAGE
    cursor = 0

    for match in PAGE_MARKER_RE.finditer(text):
        prefix = text[cursor:match.start()].strip()
        if prefix:
            sections.append((current_page, prefix))
        current_page = int(match.group(1))
        cursor = match.end()

    remainder = text[cursor:].strip()
    if remainder:
        sections.append((current_page, remainder))
    return sections

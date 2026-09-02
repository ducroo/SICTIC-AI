"""Structure of Markdown tables, wherever they come from.

Shared by spreadsheet conversion, CSV output and tables embedded in parsed
PDFs and Word documents. Kept free of heavy imports so the chunker can use it.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterator
from dataclasses import dataclass

TABLE_LINE_RE = re.compile(r"^\|")
SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")

HEADER_SCAN_ROWS = 6
MIN_HEADER_LABELS = 2
HEADER_MARGIN = 2

PROSE_SEGMENT = "prose"
TABLE_SEGMENT = "table"


@dataclass(frozen=True)
class TableBlock:
    """A table split into the lines that label it and the lines that fill it."""

    header: str
    separator: str
    rows: list[str]


def is_table_line(line: str) -> bool:
    return bool(TABLE_LINE_RE.match(line.strip()))


def split_cells(row: str) -> list[str]:
    stripped = row.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in CELL_SPLIT_RE.split(stripped)[1:-1]]


def is_separator_row(row: str) -> bool:
    cells = split_cells(row)
    return bool(cells) and all(
        SEPARATOR_CELL_RE.match(cell) for cell in cells if cell
    )


def looks_numeric(cell: str) -> bool:
    candidate = cell.replace("'", "").replace(",", "").replace("%", "")
    for symbol in ("CHF", "EUR", "USD", "$", "€"):
        candidate = candidate.replace(symbol, "")
    candidate = candidate.strip().lstrip("(").rstrip(")")
    if not candidate:
        return False
    try:
        float(candidate)
    except ValueError:
        return False
    return True


def label_count(row: str) -> int:
    return sum(
        1 for cell in split_cells(row) if cell and not looks_numeric(cell)
    )


def header_score(row: str) -> int:
    """Score a row on how much it names columns rather than holding values.

    Numbers count against a row instead of disqualifying it, because genuine
    headers do sometimes contain them, as in a row of year columns.
    """
    score = 0
    for cell in split_cells(row):
        if not cell:
            continue
        score += -1 if looks_numeric(cell) else 1
    return score


def select_header(rows: list[str]) -> int:
    """Return the index of the row that names the columns, or -1 if none does.

    Real workbooks stack title and grouping rows above the row that actually
    names the columns, so the first row is often not the useful one. A header
    is recognised by standing out from the rows beneath it rather than by any
    absolute score, since a sheet of labelled values has no header at all and
    must not have one of its value rows promoted into every chunk.
    """
    window = rows[:HEADER_SCAN_ROWS]
    if not window:
        return -1
    best_index = max(
        range(len(window)),
        key=lambda index: header_score(window[index]),
    )
    if label_count(rows[best_index]) < MIN_HEADER_LABELS:
        return -1
    body = rows[HEADER_SCAN_ROWS:] or rows[best_index + 1:]
    if not body:
        return best_index
    baseline = statistics.median(header_score(row) for row in body)
    if header_score(rows[best_index]) < baseline + HEADER_MARGIN:
        return -1
    return best_index


def parse_table(rows: list[str]) -> TableBlock:
    """Split table lines into header, separator and body.

    A GitHub-style separator row states which line is the header, so it is
    trusted when present; otherwise the header has to be inferred.
    """
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if not is_separator_row(row):
            continue
        if index == 0:
            return TableBlock(header="", separator=row, rows=rows[1:])
        return TableBlock(
            header=rows[index - 1],
            separator=row,
            rows=rows[:index - 1] + rows[index + 1:],
        )

    header_index = select_header(rows)
    if header_index < 0:
        return TableBlock(header="", separator="", rows=list(rows))
    return TableBlock(
        header=rows[header_index],
        separator="",
        rows=rows[:header_index] + rows[header_index + 1:],
    )


def iter_segments(
    text: str,
    min_table_chars: int,
) -> Iterator[tuple[str, str]]:
    """Split Markdown into prose and large-table segments.

    Only tables too big to survive chunking intact are separated out. Smaller
    ones stay with the prose around them, which is usually what explains them.
    """
    prose: list[str] = []
    table: list[str] = []

    def flush_prose() -> Iterator[tuple[str, str]]:
        body = "\n".join(prose).strip()
        prose.clear()
        if body:
            yield (PROSE_SEGMENT, body)

    def flush_table() -> Iterator[tuple[str, str]]:
        body = "\n".join(table)
        table.clear()
        if not body.strip():
            return
        if len(body) < min_table_chars:
            prose.append(body)
            return
        yield from flush_prose()
        yield (TABLE_SEGMENT, body)

    for line in text.splitlines():
        if is_table_line(line):
            table.append(line.strip())
            continue
        yield from flush_table()
        prose.append(line)

    yield from flush_table()
    yield from flush_prose()

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator

from langchain_text_splitters import MarkdownTextSplitter

from lib.markdown_tables import (
    TABLE_SEGMENT,
    TableBlock,
    iter_segments,
    parse_table,
)
from lib.datasets.models import Chunk
from lib.datasets.page_markers import UNKNOWN_PAGE, split_text_by_pages
from lib.datasets.spreadsheet_markdown import (
    is_spreadsheet_filename,
    is_spreadsheet_markdown,
    split_sheets,
)
from lib.infrastructure.document_conversion.normalization import (
    normalize_extracted_text,
)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
# Table rows are denser than prose and every chunk re-spends part of its
# budget on the repeated header, so tables get a larger window.
TABLE_CHUNK_SIZE = 2000
MAX_HEADER_CHARS = 400
MIN_BODY_CHARS = 300

PROSE_SPLITTER = MarkdownTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
)


def split_markdown(text: str, filename: str, mod_time: float) -> list[Chunk]:
    text = normalize_extracted_text(text)
    if is_spreadsheet_filename(filename) or is_spreadsheet_markdown(text):
        return split_spreadsheet(text, filename, mod_time)

    chunks: list[Chunk] = []
    for page_number, section_text in split_text_by_pages(text):
        if not section_text.strip():
            continue
        chunks.extend(
            split_section(section_text, filename, page_number, mod_time)
        )
    return chunks


def split_section(
    text: str,
    filename: str,
    page_number: int | str,
    mod_time: float,
) -> list[Chunk]:
    """Chunk one page, keeping large tables readable.

    A table too big to fit in a chunk loses its header on the first cut, which
    leaves every later chunk as unlabelled cells. Such tables are chunked on
    row boundaries with their header repeated; everything else, including
    tables small enough to survive intact, stays with its surrounding prose.
    """
    chunks: list[Chunk] = []
    for kind, segment in iter_segments(text, TABLE_CHUNK_SIZE):
        if kind == TABLE_SEGMENT:
            table = parse_table(segment.splitlines())
            chunks.extend(
                chunks_for_table(
                    table, "", filename, page_number, mod_time
                )
            )
            continue
        for doc in PROSE_SPLITTER.create_documents([segment]):
            chunks.append(
                build_chunk(doc.page_content, filename, page_number, mod_time)
            )
    return chunks


def split_spreadsheet(
    text: str,
    filename: str,
    mod_time: float,
) -> list[Chunk]:
    """Chunk a workbook so every chunk keeps the labels its numbers need."""
    chunks: list[Chunk] = []
    for sheet in split_sheets(text):
        table = TableBlock(header=sheet.header, separator="", rows=sheet.rows)
        title = f"## {sheet.name}" if sheet.name else ""
        chunks.extend(
            chunks_for_table(
                table,
                title,
                filename,
                sheet.name or UNKNOWN_PAGE,
                mod_time,
            )
        )
    return chunks


def chunks_for_table(
    table: TableBlock,
    title: str,
    filename: str,
    page_number: int | str,
    mod_time: float,
) -> list[Chunk]:
    prefix = table_prefix(table, title)
    budget = max(TABLE_CHUNK_SIZE - len(prefix), MIN_BODY_CHARS)
    bodies = list(pack_rows(table.rows, budget))
    if not bodies:
        if not prefix:
            return []
        return [build_chunk(prefix, filename, page_number, mod_time)]
    return [
        build_chunk(
            f"{prefix}\n{body}" if prefix else body,
            filename,
            page_number,
            mod_time,
        )
        for body in bodies
    ]


def table_prefix(table: TableBlock, title: str) -> str:
    lines = []
    if title:
        lines.append(title)
    if table.header:
        header = truncate_row(table.header, MAX_HEADER_CHARS)
        lines.append(header)
        # A truncated header no longer matches its separator's column count.
        if table.separator and header == table.header:
            lines.append(table.separator)
    return "\n".join(lines)


def truncate_row(row: str, limit: int) -> str:
    if len(row) <= limit:
        return row
    return row[:limit].rstrip() + " ..."


def pack_rows(rows: list[str], budget: int) -> Iterator[str]:
    """Group whole rows into bodies that fit the budget."""
    batch: list[str] = []
    length = 0
    for row in rows:
        for piece in fit_row(row, budget):
            addition = len(piece) + (1 if batch else 0)
            if batch and length + addition > budget:
                yield "\n".join(batch)
                batch = []
                length = 0
                addition = len(piece)
            batch.append(piece)
            length += addition
    if batch:
        yield "\n".join(batch)


def fit_row(row: str, budget: int) -> list[str]:
    if len(row) <= budget:
        return [row]
    return [row[start:start + budget] for start in range(0, len(row), budget)]


def build_chunk(
    content: str,
    filename: str,
    page_number: int | str,
    mod_time: float,
) -> Chunk:
    chunk_hash = hashlib.md5(
        f"{filename}_{content}".encode("utf-8")
    ).hexdigest()
    return Chunk(
        chunk_id=str(uuid.UUID(hex=chunk_hash)),
        document_name=filename,
        page_number=page_number,
        last_modified=mod_time,
        text=content,
    )

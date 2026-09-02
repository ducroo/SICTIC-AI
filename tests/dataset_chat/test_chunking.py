import hashlib
import uuid
from types import SimpleNamespace

import pytest

from lib.infrastructure.document_conversion.docling_stack.docling import (
    export_document_markdown,
)
from lib.datasets.chunking import split_markdown
from lib.datasets.models import Chunk
from lib.datasets.page_markers import format_page_marker, split_text_by_pages


def test_split_text_by_pages_without_markers():
    sections = split_text_by_pages("Plain text without page markers.")
    assert sections == [("n/a", "Plain text without page markers.")]


def test_split_text_by_pages_with_markers():
    text = (
        f"{format_page_marker(1)}\n\nFirst page text.\n\n"
        f"{format_page_marker(3)}\n\nThird page text."
    )
    sections = split_text_by_pages(text)
    assert sections == [(1, "First page text."), (3, "Third page text.")]


def test_split_markdown_assigns_real_page_numbers():
    text = (
        f"{format_page_marker(2)}\n\n"
        + ("Page two content. " * 80)
        + f"\n\n{format_page_marker(5)}\n\n"
        + ("Page five content. " * 80)
    )
    chunks = split_markdown(text, "deck.pdf", 123456789.0)

    assert chunks
    page_two_chunks = [chunk for chunk in chunks if chunk.page_number == 2]
    page_five_chunks = [chunk for chunk in chunks if chunk.page_number == 5]
    assert page_two_chunks
    assert page_five_chunks
    assert "Page two content." in page_two_chunks[0].text
    assert "Page five content." in page_five_chunks[0].text


def test_split_markdown_without_markers_uses_unknown_page():
    text = "This is a test document. " * 100
    chunks = split_markdown(text, "test_file.md", 123456789.0)

    assert chunks
    assert all(chunk.page_number == "n/a" for chunk in chunks)


def test_split_markdown_generates_stable_chunk_ids():
    text = "This is a test document. " * 100
    filename = "test_file.md"

    chunks = split_markdown(text, filename, 123456789.0)

    assert chunks
    first = chunks[0]
    expected_hash = hashlib.md5(
        f"{filename}_{first.text}".encode("utf-8")
    ).hexdigest()
    assert first.chunk_id == str(uuid.UUID(hex=expected_hash))
    assert first.document_name == filename


def test_split_markdown_rejects_dense_private_use_text():
    encoded = "".join(chr(ord(char) + 0xF002) for char in "Approved")

    with pytest.raises(ValueError, match="requires OCR"):
        split_markdown(encoded, "encoded.pdf", 123456789.0)


def test_split_markdown_replaces_sparse_private_use_symbols():
    text = "Normal extracted text with a private-use symbol: \uf0a7"

    chunks = split_markdown(text, "symbols.pdf", 123456789.0)

    assert chunks[0].text == "Normal extracted text with a private-use symbol:"


def test_chunk_to_md_omits_unknown_page():
    chunk = Chunk(
        chunk_id="1",
        document_name="notes.md",
        page_number="n/a",
        last_modified=0.0,
        text="Some content.",
    )

    assert chunk.to_md() == "### Source: notes.md\n\nSome content."


def test_export_document_markdown_adds_single_page_marker():
    document = SimpleNamespace(
        pages={1: object()},
        export_to_markdown=lambda page_no=None: "Single page body.",
    )

    markdown = export_document_markdown(document)

    assert markdown == f"{format_page_marker(1)}\n\nSingle page body."


def test_export_document_markdown_exports_each_page_separately():
    document = SimpleNamespace(
        pages={1: object(), 2: object()},
        export_to_markdown=lambda page_no=None: f"Body for page {page_no}.",
    )

    markdown = export_document_markdown(document)

    assert markdown == (
        f"{format_page_marker(1)}\n\nBody for page 1.\n\n"
        f"{format_page_marker(2)}\n\nBody for page 2."
    )

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lib.adapters.docling import ConversionStatus
from lib.adapters.llamaparse.adapter import (
    LlamaParseAdapter,
    _markdown_from_parse_result,
)


def test_markdown_from_parse_result_adds_page_markers():
    result = SimpleNamespace(
        markdown=SimpleNamespace(
            pages=[
                SimpleNamespace(markdown="Page one"),
                SimpleNamespace(markdown="Page two"),
            ]
        )
    )
    text = _markdown_from_parse_result(result)
    assert "<!-- sictic-page:1 -->" in text
    assert "Page one" in text
    assert "<!-- sictic-page:2 -->" in text
    assert "Page two" in text


@pytest.mark.asyncio
async def test_llamaparse_passthrough_markdown(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Hello\n", encoding="utf-8")
    text = await LlamaParseAdapter()._process_single_file(str(path), path.name)
    assert text == "# Hello"


@pytest.mark.asyncio
async def test_llamaparse_extract_documents_success(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    path.write_text("body", encoding="utf-8")
    adapter = LlamaParseAdapter(concurrency_limit=1)
    results = [
        item
        async for item in adapter.extract_documents(
            [{"filename": path.name, "local_path": path}]
        )
    ]
    assert len(results) == 1
    assert results[0].status is ConversionStatus.SUCCESS
    assert results[0].text == "body"

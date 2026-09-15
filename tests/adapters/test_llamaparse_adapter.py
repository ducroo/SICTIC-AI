from __future__ import annotations

from types import SimpleNamespace

import pytest

from lib.infrastructure.llamaparse.adapter import (  # pragma: allowlist secret
    convert_document,
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
async def test_saas_parser_passthrough_markdown(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Hello\n", encoding="utf-8")
    conversion = await convert_document(path)
    assert conversion.markdown == "# Hello\n"


@pytest.mark.asyncio
async def test_saas_parser_empty_source_warning(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    conversion = await convert_document(path)
    assert conversion.markdown == ""
    assert conversion.warnings == ("The source file is empty",)


@pytest.mark.asyncio
async def test_saas_parser_rejects_unsupported_format(tmp_path):
    path = tmp_path / "logo.eps"
    path.write_bytes(b"%!PS-Adobe EPSF")
    with pytest.raises(ValueError, match="Unsupported document format"):
        await convert_document(path)

from __future__ import annotations

import json

import pytest

from lib.infrastructure.document_conversion import convert_document
from lib.infrastructure.document_conversion.docling_serve import (
    DOCLING_SERVE_CONVERTER,
    convert_form_fields,
    extract_convert_payload,
)
from lib.infrastructure.document_conversion.graph_markdown import graph_to_markdown
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from tests.infrastructure.fake_docling_serve import (
    MINIMAL_PDF,
    SAMPLE_GRAPH,
    create_app as create_fake_docling_app,
    sample_markdown,
)


async def _start_fake():
    from aiohttp import web

    app = create_fake_docling_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, app, f"http://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_convert_pdf_renders_graph_and_writes_sidecar(monkeypatch, tmp_path):
    runner, app, base_url = await _start_fake()
    try:
        monkeypatch.setenv("DOCUMENT_PARSER", "docling")
        monkeypatch.setenv("DOCUMENT_CONVERTER", DOCLING_SERVE_CONVERTER)
        monkeypatch.setenv("DOCLING_SERVE_URL", base_url)
        source = tmp_path / "acme.pdf"
        source.write_bytes(MINIMAL_PDF)

        conversion = await convert_document(source)

        assert "# Acme Robotics" in conversion.markdown
        assert "| CET1 capital ratio | 14.4% |" in conversion.markdown
        assert "Media Relations" not in conversion.markdown
        sidecar = source.with_name("acme.pdf.docling.json")
        assert json.loads(sidecar.read_text(encoding="utf-8"))["name"] == (
            "acme-robotics.pdf"
        )
        assert app["state"]["uploads"][0]["filename"] == "acme.pdf"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_markdown_passthrough_skips_http(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENT_PARSER", "docling")
    monkeypatch.setenv("DOCUMENT_CONVERTER", DOCLING_SERVE_CONVERTER)
    monkeypatch.delenv("DOCLING_SERVE_URL", raising=False)
    path = tmp_path / "note.md"
    path.write_text("# Hello\n", encoding="utf-8")

    conversion = await convert_document(path)

    assert conversion.markdown == "# Hello\n"


@pytest.mark.asyncio
async def test_empty_source_returns_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENT_PARSER", "docling")
    monkeypatch.setenv("DOCUMENT_CONVERTER", DOCLING_SERVE_CONVERTER)
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")

    conversion = await convert_document(path)

    assert conversion.markdown == ""
    assert conversion.warnings == ("The source file is empty",)


@pytest.mark.asyncio
async def test_missing_url_is_configuration_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENT_PARSER", "docling")
    monkeypatch.setenv("DOCUMENT_CONVERTER", DOCLING_SERVE_CONVERTER)
    monkeypatch.delenv("DOCLING_SERVE_URL", raising=False)
    path = tmp_path / "deck.pdf"
    path.write_bytes(MINIMAL_PDF)

    with pytest.raises(InfrastructureError) as raised:
        await convert_document(path)

    assert raised.value.kind is InfrastructureErrorKind.CONFIGURATION
    assert "DOCLING_SERVE_URL" in str(raised.value)


def test_extract_convert_payload_reads_graph_and_markdown():
    markdown, graph, errors = extract_convert_payload(
        {
            "document": {
                "md_content": "# fallback\n",
                "json_content": SAMPLE_GRAPH,
            },
            "errors": None,
        }
    )
    assert markdown.startswith("# fallback")
    assert graph == SAMPLE_GRAPH
    assert errors is None
    assert "Acme Robotics" in graph_to_markdown(graph)


def test_convert_form_fields_flatten_lists_and_bools():
    fields = convert_form_fields(
        {"to_formats": ["json", "md"], "do_ocr": True, "table_mode": "accurate"}
    )
    assert ("to_formats", "json") in fields
    assert ("to_formats", "md") in fields
    assert ("do_ocr", "true") in fields
    assert ("table_mode", "accurate") in fields


def test_sample_markdown_matches_graph_renderer():
    assert sample_markdown() == graph_to_markdown(SAMPLE_GRAPH)

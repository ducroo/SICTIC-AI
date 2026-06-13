import pytest
from openpyxl import Workbook

from lib.adapters.docling import (
    DoclingAdapter,
    SPREADSHEET_MARKDOWN_MARKER,
    _chat_completions_model,
    _chat_completions_url,
)


def test_docling_sdk_import_available():
    from docling.document_converter import DocumentConverter

    assert DocumentConverter is not None


def test_rtf_conversion_extracts_text_without_docling(tmp_path):
    path = tmp_path / "readme.rtf"
    path.write_text(
        r"{\rtf1\ansi\ansicpg1252 This folder contains:\par Confidential caf\'e9.}",
        encoding="latin-1",
    )

    markdown = DoclingAdapter._convert_rtf_sync(str(path))

    assert markdown == "This folder contains:\nConfidential café.\n"


@pytest.mark.asyncio
async def test_rtf_processing_bypasses_docling_converter(monkeypatch, tmp_path):
    path = tmp_path / "readme.rtf"
    path.write_text(r"{\rtf1\ansi Plain text.}", encoding="latin-1")

    async def acquire(_limit):
        return None

    monkeypatch.setattr("lib.services_gateway.gateway.acquire_docling_slot", acquire)
    monkeypatch.setattr("lib.services_gateway.gateway.release_docling_slot", lambda: None)
    monkeypatch.setattr(
        DoclingAdapter,
        "_convert_sync",
        staticmethod(lambda _path: pytest.fail("Docling converter should not handle RTF")),
    )

    text = await DoclingAdapter()._process_single_file(str(path), "readme.rtf")

    assert text == "Plain text.\n"


def test_spreadsheet_conversion_omits_formatting_only_cells(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "financial model"
    sheet["A1"] = "Revenue"
    sheet["B2"] = 1200
    sheet.merge_cells("A5:XFD5")

    path = tmp_path / "model.xlsx"
    workbook.save(path)

    markdown = DoclingAdapter._convert_spreadsheet_sync(str(path))

    assert markdown.startswith(SPREADSHEET_MARKDOWN_MARKER)
    assert "## financial model" in markdown
    assert "Revenue" in markdown
    assert "1200" in markdown
    assert len(markdown) < 1_000
    assert "XFD" not in markdown


def test_spreadsheet_conversion_omits_formulas_without_cached_values(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Name"
    sheet["B1"] = "Amount"
    sheet["A2"] = "Seed"
    sheet["B2"] = "=40+60"

    path = tmp_path / "normal.xlsx"
    workbook.save(path)

    markdown = DoclingAdapter._convert_spreadsheet_sync(str(path))

    assert "Seed" in markdown
    assert "=40+60" not in markdown


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [".xls", ".xlsx", ".xlsm"])
async def test_spreadsheet_processing_bypasses_docling_converter(monkeypatch, tmp_path, extension):
    path = tmp_path / f"model{extension}"
    path.write_bytes(b"workbook")

    async def acquire(_limit):
        return None

    monkeypatch.setattr("lib.services_gateway.gateway.acquire_docling_slot", acquire)
    monkeypatch.setattr("lib.services_gateway.gateway.release_docling_slot", lambda: None)
    monkeypatch.setattr(
        DoclingAdapter,
        "_convert_spreadsheet_sync",
        staticmethod(lambda _path: "compact values\n"),
    )
    monkeypatch.setattr(
        DoclingAdapter,
        "_convert_sync",
        staticmethod(lambda _path: pytest.fail("Docling converter should not handle spreadsheets")),
    )

    text = await DoclingAdapter()._process_single_file(str(path), path.name)

    assert text == "compact values\n"


def test_repaired_pdf_conversion_runs_ghostscript_then_docling(monkeypatch, tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF\n")
    calls = {}

    monkeypatch.setattr("lib.adapters.docling.shutil.which", lambda name: "/usr/bin/gs")

    def fake_run(cmd, check, stdout, stderr):
        calls["cmd"] = cmd
        output_arg = next(item for item in cmd if item.startswith("-sOutputFile="))
        repaired = output_arg.split("=", 1)[1]
        assert cmd[-1] == str(source)
        with open(repaired, "wb") as f:
            f.write(b"%PDF-1.4 repaired\n%%EOF\n")

    monkeypatch.setattr("lib.adapters.docling.subprocess.run", fake_run)
    monkeypatch.setattr(
        DoclingAdapter,
        "_convert_sync",
        staticmethod(lambda path: f"converted {path.endswith('.pdf')}"),
    )

    markdown = DoclingAdapter._convert_repaired_pdf_sync(str(source))

    assert markdown == "converted True"
    assert calls["cmd"][0] == "/usr/bin/gs"
    assert "-sDEVICE=pdfwrite" in calls["cmd"]


def test_chat_completions_url_does_not_duplicate_v1():
    assert _chat_completions_url("http://localhost:8080/v1") == (
        "http://localhost:8080/v1/chat/completions"
    )
    assert _chat_completions_url("http://localhost:11434") == (
        "http://localhost:11434/v1/chat/completions"
    )


def test_chat_completions_model_strips_ollama_prefix_only_for_ollama_host():
    assert _chat_completions_model("http://localhost:11434", "ollama/qwen3-vl:8b") == (
        "qwen3-vl:8b"
    )
    assert _chat_completions_model("http://localhost:8080/v1", "ollama/qwen3-vl:8b") == (
        "ollama/qwen3-vl:8b"
    )

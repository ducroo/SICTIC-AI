from openpyxl import Workbook

from lib.adapters.docling import (
    DoclingAdapter,
    _chat_completions_model,
    _chat_completions_url,
)


def test_docling_sdk_import_available():
    from docling.document_converter import DocumentConverter

    assert DocumentConverter is not None


def test_spreadsheet_fallback_detects_excel_wide_merged_range(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "financial model"
    sheet["A1"] = "Revenue"
    sheet["B2"] = 1200
    sheet.merge_cells("A5:XFD5")

    path = tmp_path / "model.xlsx"
    workbook.save(path)

    assert DoclingAdapter._spreadsheet_needs_compact_fallback(str(path)) is True

    markdown = DoclingAdapter._convert_spreadsheet_sync(str(path))

    assert "## financial model" in markdown
    assert "Revenue" in markdown
    assert "1200" in markdown
    assert len(markdown) < 1_000
    assert "XFD" not in markdown


def test_spreadsheet_fallback_ignores_normal_workbook(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Name"
    sheet["B1"] = "Amount"
    sheet["A2"] = "Seed"
    sheet["B2"] = 100

    path = tmp_path / "normal.xlsx"
    workbook.save(path)

    assert DoclingAdapter._spreadsheet_needs_compact_fallback(str(path)) is False


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

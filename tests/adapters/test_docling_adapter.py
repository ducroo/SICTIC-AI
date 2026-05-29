from openpyxl import Workbook

from lib.adapters.docling import DoclingAdapter


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

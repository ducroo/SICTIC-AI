from __future__ import annotations

from lib.logger import get_logger

logger = get_logger(__name__)

SPREADSHEET_EXTENSIONS = (".xls", ".xlsx", ".xlsm")
SPREADSHEET_MARKDOWN_MARKER = (
    "<!-- sictic-spreadsheet: compact-values-v2 -->"
)


def is_spreadsheet_filename(filename: str) -> bool:
    return filename.lower().endswith(SPREADSHEET_EXTENSIONS)


def convert_spreadsheet(filepath: str) -> str:
    """Convert spreadsheets to compact, value-only Markdown."""
    if filepath.lower().endswith(".xls"):
        return convert_xls(filepath)
    return convert_openpyxl(filepath)


def convert_openpyxl(filepath: str) -> str:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    values_wb = load_workbook(filepath, read_only=False, data_only=True)
    formulas_wb = load_workbook(filepath, read_only=False, data_only=False)
    sections = []
    missing_cached_formulas = 0
    try:
        for values_ws, formulas_ws in zip(
            values_wb.worksheets,
            formulas_wb.worksheets,
        ):
            if values_ws.sheet_state != "visible":
                continue

            def is_hidden(row: int, column: int) -> bool:
                row_dimension = values_ws.row_dimensions.get(row)
                if row_dimension is not None and row_dimension.hidden:
                    return True
                column_dimension = values_ws.column_dimensions.get(
                    get_column_letter(column)
                )
                return bool(
                    column_dimension is not None
                    and column_dimension.hidden
                )

            row_cells: dict[int, dict[int, str]] = {}
            for (row, col), cell in values_ws._cells.items():
                if is_hidden(row, col) or cell.data_type == "e":
                    continue
                value = cell.value
                text = (
                    ""
                    if value is None
                    else str(value).replace("\n", " ").strip()
                )
                if text:
                    row_cells.setdefault(row, {})[col] = text
            for (row, col), formula_cell in formulas_ws._cells.items():
                if is_hidden(row, col):
                    continue
                cached_cell = values_ws._cells.get((row, col))
                if (
                    formula_cell.data_type == "f"
                    and (
                        cached_cell is None
                        or cached_cell.value in (None, "")
                    )
                ):
                    missing_cached_formulas += 1

            if not row_cells:
                continue
            sections.append(f"## {values_ws.title}")
            for row_index in sorted(row_cells):
                columns = row_cells[row_index]
                row = [
                    columns.get(column_index, "")
                    for column_index in range(1, max(columns) + 1)
                ]
                sections.append(
                    "| "
                    + " | ".join(
                        escape_markdown_cell(cell) for cell in row
                    )
                    + " |"
                )
            sections.append("")
    finally:
        values_wb.close()
        formulas_wb.close()

    if missing_cached_formulas:
        logger.warning(
            "Spreadsheet conversion omitted %s formula cells without "
            "cached values: %s",
            missing_cached_formulas,
            filepath,
        )
    return render_spreadsheet_markdown(sections)


def convert_xls(filepath: str) -> str:
    import xlrd

    workbook = xlrd.open_workbook(filepath, on_demand=True)
    sections = []
    try:
        for sheet in workbook.sheets():
            rows = []
            for row_index in range(sheet.nrows):
                row_info = sheet.rowinfo_map.get(row_index)
                if row_info is not None and row_info.hidden:
                    continue
                values = [
                    ""
                    if (
                        (column_info := sheet.colinfo_map.get(column_index))
                        is not None
                        and column_info.hidden
                    )
                    else xls_cell_text(
                        sheet.cell_value(row_index, column_index)
                    )
                    for column_index in range(sheet.ncols)
                ]
                while values and not values[-1]:
                    values.pop()
                if any(values):
                    rows.append(values)
            if not rows:
                continue
            sections.append(f"## {sheet.name}")
            sections.extend(
                "| "
                + " | ".join(
                    escape_markdown_cell(value) for value in row
                )
                + " |"
                for row in rows
            )
            sections.append("")
    finally:
        workbook.release_resources()
    return render_spreadsheet_markdown(sections)


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def render_spreadsheet_markdown(sections: list[str]) -> str:
    body = "\n".join(sections).strip()
    if not body:
        return f"{SPREADSHEET_MARKDOWN_MARKER}\n"
    return f"{SPREADSHEET_MARKDOWN_MARKER}\n\n{body}\n"


def xls_cell_text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\n", " ").strip()

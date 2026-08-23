import datetime

import pytest

from lib.adapters.docling.spreadsheets import format_cell_value
from lib.datasets.chunking import split_markdown
from lib.datasets.markdown_tables import select_header
from lib.datasets.spreadsheet_markdown import (
    SPREADSHEET_MARKDOWN_MARKER,
    is_spreadsheet_markdown,
    split_sheets,
)

HEADER = "| Shareholder | Category | Shares | Ownership |"


def sheet_markdown(*sheets: tuple[str, list[str]]) -> str:
    body = "\n\n".join(
        "\n".join([f"## {name}", *rows]) for name, rows in sheets
    )
    return f"{SPREADSHEET_MARKDOWN_MARKER}\n\n{body}\n"


def investor_rows(count: int) -> list[str]:
    return [
        f"| Investor {index} | BA | {1000 + index} | 0.0{index:02d} |"
        for index in range(count)
    ]


def test_select_header_prefers_labelled_row_over_title_rows():
    rows = [
        "|  | Round Jan 25 |  |  |",
        "|  |  | valuation | shares |",
        "| Category | Cash-in | Common Shares | Total Shares |",
        "| Founders |  | 86380 | 86380 |",
    ]

    assert select_header(rows) == 2


def test_select_header_reports_none_when_no_row_carries_labels():
    assert select_header(["| 1 | 2 | 3 |", "| 4 | 5 | 6 |"]) == -1


def test_select_header_rejects_a_value_row_that_happens_to_have_labels():
    rows = [
        "|  | Pre-money valuation | CHF | 3500000 |",
        "|  | Post-money valuation | CHF | 4345000 |",
    ]

    assert select_header(rows) == -1


def test_select_header_keeps_a_genuine_header_of_year_columns():
    rows = [
        "| Position | 2023 | 2024 | 2025 | 2026 | share |",
        "| Revenue | 100 | 200 | 300 | 400 | 0.12 |",
    ]

    assert select_header(rows) == 0


def test_split_sheets_separates_header_from_body():
    text = sheet_markdown(("Cap Table", [HEADER, *investor_rows(3)]))

    sections = split_sheets(text)

    assert len(sections) == 1
    assert sections[0].name == "Cap Table"
    assert sections[0].header == HEADER
    assert len(sections[0].rows) == 3
    assert HEADER not in sections[0].rows


def test_every_chunk_repeats_the_sheet_title_and_header():
    text = sheet_markdown(("Cap Table", [HEADER, *investor_rows(200)]))

    chunks = split_markdown(text, "cap.xlsx", 0.0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith(f"## Cap Table\n{HEADER}\n")
        assert chunk.text.count(HEADER) == 1


def test_chunks_are_attributed_to_their_worksheet():
    text = sheet_markdown(
        ("Cap Table", [HEADER, *investor_rows(60)]),
        ("Runway", ["| Month | Burn |", "| Jan | -64000 |"]),
    )

    chunks = split_markdown(text, "model.xlsx", 0.0)

    assert {chunk.page_number for chunk in chunks} == {"Cap Table", "Runway"}
    runway = [chunk for chunk in chunks if chunk.page_number == "Runway"]
    assert len(runway) == 1
    assert "| Jan | -64000 |" in runway[0].text


def test_rows_are_never_split_across_chunks():
    text = sheet_markdown(("Cap Table", [HEADER, *investor_rows(200)]))

    chunks = split_markdown(text, "cap.xlsx", 0.0)

    emitted = [
        line
        for chunk in chunks
        for line in chunk.text.splitlines()
        if line.startswith("| Investor ")
    ]
    assert emitted == investor_rows(200)


def test_oversized_row_is_split_but_keeps_its_header():
    giant = "| Notes | " + ("commentary " * 900) + "|"
    text = sheet_markdown(("Cap Table", [HEADER, giant]))

    chunks = split_markdown(text, "cap.xlsx", 0.0)

    assert len(chunks) > 1
    assert all(HEADER in chunk.text for chunk in chunks)


def test_sheet_with_only_a_header_still_produces_a_chunk():
    text = sheet_markdown(("Empty", [HEADER]))

    chunks = split_markdown(text, "cap.xlsx", 0.0)

    assert len(chunks) == 1
    assert chunks[0].text == f"## Empty\n{HEADER}"


def test_markdown_without_the_marker_uses_the_prose_splitter():
    text = "## Cap Table\n" + HEADER + "\n" + "\n".join(investor_rows(200))

    chunks = split_markdown(text, "cap.md", 0.0)

    assert any(HEADER not in chunk.text for chunk in chunks)


def test_previously_parsed_spreadsheets_are_still_recognised():
    legacy = "<!-- sictic-spreadsheet: compact-values-v1 -->\n\n## S\n| a | b |"

    assert is_spreadsheet_markdown(legacy)


@pytest.mark.parametrize(
    "value,number_format,expected",
    [
        (None, "", ""),
        (72310, "", "72310"),
        (1.0, "", "1"),
        (15.151515151515152, "", "15.15"),
        (8136.825000000001, "", "8136.83"),
        (0.24685415429152754, "", "0.2469"),
        (0.002, "", "0.002"),
        (0.0000123, "", "1.23e-05"),
        (0.24685415429152754, "0.00%", "24.69%"),
        (True, "", "TRUE"),
        (False, "", "FALSE"),
        (datetime.datetime(2026, 1, 19), "", "2026-01-19"),
        (datetime.datetime(2026, 1, 19, 14, 30), "", "2026-01-19 14:30"),
        (datetime.date(2026, 3, 16), "", "2026-03-16"),
        ("  spaced  text  ", "", "spaced  text"),
    ],
)
def test_format_cell_value(value, number_format, expected):
    assert format_cell_value(value, number_format) == expected

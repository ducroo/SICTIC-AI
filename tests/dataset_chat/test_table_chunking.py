from lib.datasets.chunking import TABLE_CHUNK_SIZE, split_markdown
from lib.markdown_tables import (
    PROSE_SEGMENT,
    TABLE_SEGMENT,
    iter_segments,
    is_separator_row,
    parse_table,
)
from lib.datasets.page_markers import format_page_marker

HEADER = "| Ortschaftsname | PLZ4 | Gemeindename | Kanton |"
SEPARATOR = "|----------------|------|--------------|--------|"


def place_rows(count: int) -> list[str]:
    return [
        f"| Lausanne {index} | {1000 + index} | Lausanne | VD |"
        for index in range(count)
    ]


def csv_markdown(count: int) -> str:
    return "\n".join([HEADER, SEPARATOR, *place_rows(count)])


def test_is_separator_row():
    assert is_separator_row(SEPARATOR)
    assert is_separator_row("| :--- | ---: |")
    assert not is_separator_row(HEADER)


def test_parse_table_trusts_the_separator_row():
    table = parse_table([HEADER, SEPARATOR, *place_rows(3)])

    assert table.header == HEADER
    assert table.separator == SEPARATOR
    assert table.rows == place_rows(3)


def test_parse_table_infers_a_header_without_a_separator():
    table = parse_table([HEADER, *place_rows(8)])

    assert table.header == HEADER
    assert table.separator == ""
    assert HEADER not in table.rows


def test_small_tables_stay_with_their_prose():
    text = (
        "The round is summarised below.\n\n"
        f"{HEADER}\n{SEPARATOR}\n" + "\n".join(place_rows(2))
    )

    segments = list(iter_segments(text, TABLE_CHUNK_SIZE))

    assert [kind for kind, _body in segments] == [PROSE_SEGMENT]
    assert HEADER in segments[0][1]


def test_large_tables_are_separated_from_prose():
    text = "Intro paragraph.\n\n" + csv_markdown(200) + "\n\nClosing note."

    segments = list(iter_segments(text, TABLE_CHUNK_SIZE))

    assert [kind for kind, _body in segments] == [
        PROSE_SEGMENT,
        TABLE_SEGMENT,
        PROSE_SEGMENT,
    ]
    assert segments[0][1] == "Intro paragraph."
    assert segments[2][1] == "Closing note."


def test_every_chunk_of_a_large_table_repeats_the_header():
    chunks = split_markdown(csv_markdown(400), "places.csv", 0.0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith(f"{HEADER}\n{SEPARATOR}\n")
        assert chunk.text.count(HEADER) == 1


def test_large_table_rows_survive_intact():
    chunks = split_markdown(csv_markdown(400), "places.csv", 0.0)

    emitted = [
        line
        for chunk in chunks
        for line in chunk.text.splitlines()
        if line.startswith("| Lausanne ")
    ]
    assert emitted == place_rows(400)


def test_table_chunks_keep_the_page_they_came_from():
    text = (
        f"{format_page_marker(4)}\n\nIntro paragraph.\n\n" + csv_markdown(200)
    )

    chunks = split_markdown(text, "report.pdf", 0.0)

    assert chunks
    assert all(chunk.page_number == 4 for chunk in chunks)


def test_prose_only_documents_are_unaffected():
    text = "This is a test document. " * 100

    chunks = split_markdown(text, "notes.md", 0.0)

    assert chunks
    assert all(chunk.page_number == "n/a" for chunk in chunks)
    assert "This is a test document." in chunks[0].text

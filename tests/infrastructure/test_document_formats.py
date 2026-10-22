import io
import zipfile

import pytest

from lib.infrastructure.document_formats import decode_document_text, detect_document_extension


def office_bytes(member, content_types=b"<Types/>"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        # Do not rely on file order or the first few ZIP members.
        for number in range(8):
            archive.writestr(f"docProps/extra{number}.xml", "<properties/>")
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr(member, "<document/>")
    return output.getvalue()


@pytest.mark.parametrize(("content", "extension"), [
    (b"%PDF-1.7\nbody", ".pdf"),
    (b"<!DOCTYPE html><html><body>Home</body></html>", ".html"),
    (b"<!-- redirect -->\n<h1>Home</h1>", ".html"),
    (b"{\\rtf1\\ansi Hello}", ".rtf"),
    (b'{"team": ["Jane"]}', ".json"),
    (b'{"html": "<h1>Home</h1>"}', ".json"),
    (b"A literal example: <p>text</p>", ".txt"),
    (b"Plain company information.", ".txt"),
    ("Company information".encode("utf-16"), ".txt"),
    (b"", None),
    (b"\x00\x01\x02unknown", None),
    (b"PK\x03\x04broken", None),
    (b"\x89PNG\r\n\x1a\nimage", None),
    (b"<?xml version='1.0'?><unknown/>", None),
])
def test_content_overrides_pdf_url_and_header(content, extension):
    assert detect_document_extension(
        content, filename="https://example.com/deck.pdf", content_type="application/pdf",
    ) == extension


@pytest.mark.parametrize(("member", "extension"), [
    ("word/document.xml", ".docx"),
    ("xl/workbook.xml", ".xlsx"),
    ("ppt/presentation.xml", ".pptx"),
])
def test_office_type_comes_from_archive_contents(member, extension):
    assert detect_document_extension(
        office_bytes(member), filename="wrong.pdf", content_type="text/html",
    ) == extension


def test_macro_enabled_spreadsheet_keeps_its_format():
    assert detect_document_extension(office_bytes(
        "xl/workbook.xml", b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    )) == ".xlsm"


def test_generic_zip_is_not_an_office_document():
    assert detect_document_extension(office_bytes("notes.txt"), filename="deck.docx") is None


@pytest.mark.parametrize(("content", "filename", "extension"), [
    (b"Name,Role\nJane,Founder\n", "team.csv", ".csv"),
    (b"No spreadsheet here", "team.csv", ".txt"),
    (b"# Team\nJane is the founder", "team.md", ".md"),
    (b"<h1>Error</h1>", "team.md", ".html"),
])
def test_hints_only_disambiguate_verified_text(content, filename, extension):
    assert detect_document_extension(content, filename=filename) == extension


@pytest.mark.parametrize("header", ["text/html; charset=windows-1252", "application/pdf"])
def test_html_encoding_can_come_from_http_or_page_metadata(header):
    content = b'<meta charset="windows-1252"><h1>Z\xfcrich</h1>'
    assert detect_document_extension(content, filename="wrong.pdf", content_type=header) == ".html"
    assert "Zürich" in decode_document_text(content, content_type=header)


def test_unknown_charset_is_skipped():
    assert detect_document_extension(b"\xff", content_type="text/plain; charset=invalid") is None

"""Render pitch-deck review HTML to a landscape PDF (Chromium print)."""

from __future__ import annotations

import base64
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

_SPIKE_DIR = Path(__file__).resolve().parent
_DEFAULT_LOGO = _SPIKE_DIR / "hosting" / "public" / "static" / "sictic-logo.svg"
_FALLBACK_LOGO = _SPIKE_DIR / "static" / "sictic-logo.svg"

# Print layout uses stacked rows instead of HTML tables. Fixed six-column
# table widths crushed the seventh DD column (proposed next steps) and made
# Chromium emit hundreds of mostly-blank pages.
_PRINT_CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
  max-width: 100%;
  font-family: Figtree, Helvetica, Arial, sans-serif;
  color: #212529;
  font-size: 9pt;
  line-height: 1.35;
  background: #fff;
}
.report-masthead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12pt;
  padding-bottom: 8pt;
  margin-bottom: 10pt;
  border-bottom: 1pt solid #d2d6dc;
  break-inside: avoid;
  page-break-inside: avoid;
}
.report-logo { height: 28pt; width: auto; display: block; }
.report-logo-text {
  margin: 0;
  color: #bc2132;
  font-weight: 700;
  font-size: 16pt;
}
.report-kicker {
  margin: 0 0 2pt;
  color: #607382;
  font-size: 8pt;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
h1, h2, h3 {
  font-family: Montserrat, Figtree, Helvetica, Arial, sans-serif;
  line-height: 1.2;
}
.report-masthead h2 { margin: 0; font-size: 14pt; }
.report-body h1 { font-size: 13pt; margin: 0 0 8pt; }
.report-body h2 {
  font-size: 11pt;
  margin: 12pt 0 6pt;
  padding-bottom: 3pt;
  border-bottom: 1.5pt solid #f0d5d8;
}
.report-body h3 { font-size: 10pt; margin: 10pt 0 4pt; }
.table-wrap { overflow: visible; margin: 8pt 0; max-width: 100%; }
.print-table { width: 100%; }
.print-row {
  break-inside: auto;
  page-break-inside: auto;
  border-bottom: 0.5pt solid #d2d6dc;
  padding: 5pt 0 7pt;
  margin: 0;
}
.print-row:nth-child(even) { background: #fcfcfc; }
.print-kv {
  display: grid;
  grid-template-columns: 28mm 1fr;
  gap: 3pt 6pt;
  padding: 1.5pt 0;
  align-items: start;
}
.print-label {
  color: #607382;
  font-size: 7pt;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.print-value {
  overflow-wrap: anywhere;
  word-break: break-word;
  font-size: 7.5pt;
}
.status-pill {
  display: inline-block;
  padding: 1pt 4pt;
  border-radius: 8pt;
  font-size: 7pt;
  font-weight: 700;
  line-height: 1.2;
  white-space: normal;
}
.status-fine { color: #0b6e4f; background: #e8f6f0; }
.status-sufficient { color: #0070ad; background: #e8f3fa; }
.status-borderline { color: #b85f00; background: #fff1e0; }
.status-critical { color: #bc2132; background: #fdecee; }
.status-missing { color: #607382; background: #eef1f4; }
.report-footnote {
  margin-top: 12pt;
  padding-top: 6pt;
  border-top: 0.5pt solid #d2d6dc;
  color: #607382;
  font-size: 8pt;
}
"""


def logo_path() -> Path | None:
    for candidate in (_DEFAULT_LOGO, _FALLBACK_LOGO):
        if candidate.is_file():
            return candidate
    return None


def logo_data_uri(logo: Path | None = None) -> str | None:
    """Inline the logo so Chromium print does not depend on file:// URLs."""
    logo_file = logo if logo is not None else logo_path()
    if logo_file is None or not logo_file.is_file():
        return None
    payload = base64.standard_b64encode(logo_file.read_bytes()).decode("ascii")
    suffix = logo_file.suffix.lower()
    if suffix == ".svg":
        mime = "image/svg+xml"
    elif suffix == ".png":
        mime = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    else:
        mime = "application/octet-stream"
    return f"data:{mime};base64,{payload}"


def normalize_report_body_html(report_body_html: str) -> str:
    """Restore line breaks escaped by the markdown table renderer."""
    text = report_body_html or ""
    text = re.sub(r"&lt;br\s*/?&gt;", "<br>", text, flags=re.IGNORECASE)
    return text.strip()


class _TableFlattenParser(HTMLParser):
    """Rewrite HTML tables into labeled stacked rows for Chromium print."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_table = False
        self._in_thead = False
        self._in_cell = False
        self._headers: list[str] = []
        self._row_cells: list[str] = []
        self._cell_parts: list[str] = []
        self._body_rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        if tag == "table" and not self._in_table:
            self._in_table = True
            self._headers = []
            self._body_rows = []
            return
        if not self._in_table:
            self.parts.append(self._render_start(tag, attr_map))
            return
        if tag == "thead":
            self._in_thead = True
            return
        if tag == "tr":
            self._row_cells = []
            return
        if tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
            return
        if self._in_cell:
            self._cell_parts.append(self._render_start(tag, attr_map))

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self.parts.append(self._render_print_table())
            self._in_table = False
            self._in_thead = False
            self._in_cell = False
            return
        if not self._in_table:
            self.parts.append(f"</{tag}>")
            return
        if tag == "thead":
            self._in_thead = False
            return
        if tag in {"td", "th"} and self._in_cell:
            cell_html = "".join(self._cell_parts).strip()
            self._row_cells.append(cell_html)
            self._in_cell = False
            self._cell_parts = []
            return
        if tag == "tr":
            if self._in_thead and not self._headers:
                self._headers = [
                    re.sub(r"<[^>]+>", "", cell).strip() or f"Column {index + 1}"
                    for index, cell in enumerate(self._row_cells)
                ]
            elif not self._in_thead:
                self._body_rows.append(list(self._row_cells))
            self._row_cells = []
            return
        if self._in_cell:
            self._cell_parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(escape(data))
        elif not self._in_table:
            self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        text = f"&{name};"
        if self._in_cell:
            self._cell_parts.append(text)
        elif not self._in_table:
            self.parts.append(text)

    def handle_charref(self, name: str) -> None:
        text = f"&#{name};"
        if self._in_cell:
            self._cell_parts.append(text)
        elif not self._in_table:
            self.parts.append(text)

    @staticmethod
    def _render_start(tag: str, attr_map: dict[str, str]) -> str:
        if not attr_map:
            return f"<{tag}>"
        attrs = " ".join(
            f'{key}="{escape(value, quote=True)}"' for key, value in attr_map.items()
        )
        return f"<{tag} {attrs}>"

    def _render_print_table(self) -> str:
        if not self._body_rows:
            return ""
        headers = list(self._headers)
        width = max([len(headers), *(len(row) for row in self._body_rows)], default=0)
        while len(headers) < width:
            headers.append(f"Column {len(headers) + 1}")
        rows_html: list[str] = []
        for row in self._body_rows:
            cells = list(row) + [""] * (width - len(row))
            # Chapter banner rows are mostly empty; keep only filled cells.
            pairs = [
                (headers[index], cells[index])
                for index in range(width)
                if cells[index].strip()
            ]
            if not pairs:
                continue
            fields = "".join(
                f'<div class="print-kv"><div class="print-label">{escape(label)}</div>'
                f'<div class="print-value">{value}</div></div>'
                for label, value in pairs
            )
            rows_html.append(f'<div class="print-row">{fields}</div>')
        if not rows_html:
            return ""
        return '<div class="print-table">' + "".join(rows_html) + "</div>"


def flatten_tables_for_print(report_body_html: str) -> str:
    """Convert checklist tables into stacked labeled rows for PDF print."""
    parser = _TableFlattenParser()
    parser.feed(report_body_html or "")
    parser.close()
    return "".join(parser.parts)


def build_report_document_html(
    *,
    deck_filename: str,
    report_body_html: str,
    logo: Path | None = None,
    kicker: str = "SICTIC pitch deck review",
    footnote: str | None = None,
) -> str:
    """Full HTML document styled like Hosting print output."""
    title = escape(f"Review of {deck_filename}")
    logo_uri = logo_data_uri(logo)
    if logo_uri is not None:
        logo_html = (
            f'<img class="report-logo" src="{logo_uri}" alt="SICTIC">'
        )
    else:
        logo_html = '<p class="report-logo-text">SICTIC</p>'
    body = flatten_tables_for_print(normalize_report_body_html(report_body_html))
    note = footnote or (
        "This is an automated document check against SICTIC Investor Day criteria. "
        "It is not a jury decision and does not submit an application."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>{_PRINT_CSS}</style>
</head>
<body>
  <article class="report-document">
    <div class="report-masthead">
      {logo_html}
      <div>
        <p class="report-kicker">{escape(kicker)}</p>
        <h2>{title}</h2>
      </div>
    </div>
    <div class="report-body">{body}</div>
    <p class="report-footnote">{escape(note)}</p>
  </article>
</body>
</html>
"""


def _pdf_via_playwright(document: str) -> bytes:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(document, wait_until="load")
            pdf = page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                margin={
                    "top": "10mm",
                    "bottom": "10mm",
                    "left": "10mm",
                    "right": "10mm",
                },
            )
        finally:
            browser.close()
    return bytes(pdf)


def _pdf_via_weasyprint(document: str) -> bytes:
    from weasyprint import HTML

    pdf = HTML(string=document, base_url=str(_SPIKE_DIR)).write_pdf()
    if not pdf:
        raise RuntimeError("WeasyPrint produced an empty PDF.")
    return bytes(pdf)


def render_report_pdf(
    *,
    deck_filename: str,
    report_body_html: str,
    logo: Path | None = None,
    kicker: str = "SICTIC pitch deck review",
    footnote: str | None = None,
) -> bytes:
    """Return PDF bytes using Chromium print (same idea as browser Print)."""
    document = build_report_document_html(
        deck_filename=deck_filename,
        report_body_html=report_body_html,
        logo=logo,
        kicker=kicker,
        footnote=footnote,
    )
    errors: list[str] = []
    try:
        pdf = _pdf_via_playwright(document)
        engine = "playwright"
    except Exception as error:
        errors.append(f"playwright: {error}")
        try:
            pdf = _pdf_via_weasyprint(document)
            engine = "weasyprint"
        except Exception as fallback_error:
            errors.append(f"weasyprint: {fallback_error}")
            raise RuntimeError(
                "PDF generation failed (" + "; ".join(errors) + ")"
            ) from fallback_error

    logger.info(
        "Rendered review PDF for %s via %s (%s bytes)",
        deck_filename,
        engine,
        len(pdf),
    )
    return pdf

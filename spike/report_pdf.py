"""Render pitch-deck review HTML to a landscape PDF (Chromium print)."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

_SPIKE_DIR = Path(__file__).resolve().parent
_DEFAULT_LOGO = _SPIKE_DIR / "hosting" / "public" / "static" / "sictic-logo.svg"
_FALLBACK_LOGO = _SPIKE_DIR / "static" / "sictic-logo.svg"

# Matches the Hosting @media print table layout.
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
table {
  border-collapse: collapse;
  width: 100%;
  max-width: 100%;
  table-layout: fixed;
  font-size: 7.5pt;
}
th, td {
  text-align: left;
  vertical-align: top;
  padding: 3pt 3.5pt;
  border-bottom: 0.5pt solid #d2d6dc;
  overflow-wrap: anywhere;
  word-break: break-word;
}
th:nth-child(1), td:nth-child(1) { width: 3.5%; }
th:nth-child(2), td:nth-child(2) { width: 11%; }
th:nth-child(3), td:nth-child(3) { width: 7.5%; }
th:nth-child(4), td:nth-child(4) { width: 28%; }
th:nth-child(5), td:nth-child(5) { width: 25%; }
th:nth-child(6), td:nth-child(6) { width: 25%; }
thead th {
  background: #fafafa;
  font-size: 7pt;
  text-transform: uppercase;
  color: #607382;
}
tbody tr:nth-child(even) { background: #fcfcfc; }
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
tr { break-inside: avoid; page-break-inside: avoid; }
"""


def logo_path() -> Path | None:
    for candidate in (_DEFAULT_LOGO, _FALLBACK_LOGO):
        if candidate.is_file():
            return candidate
    return None


def normalize_report_body_html(report_body_html: str) -> str:
    """Restore line breaks escaped by the markdown table renderer."""
    text = report_body_html or ""
    text = re.sub(r"&lt;br\s*/?&gt;", "<br>", text, flags=re.IGNORECASE)
    return text.strip()


def build_report_document_html(
    *,
    deck_filename: str,
    report_body_html: str,
    logo: Path | None = None,
) -> str:
    """Full HTML document styled like Hosting print output."""
    title = escape(f"Review of {deck_filename}")
    logo_file = logo if logo is not None else logo_path()
    if logo_file is not None:
        logo_uri = logo_file.resolve().as_uri()
        logo_html = (
            f'<img class="report-logo" src="{escape(logo_uri)}" alt="SICTIC">'
        )
    else:
        logo_html = '<p class="report-logo-text">SICTIC</p>'
    body = normalize_report_body_html(report_body_html)
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
        <p class="report-kicker">SICTIC pitch deck review</p>
        <h2>{title}</h2>
      </div>
    </div>
    <div class="report-body">{body}</div>
    <p class="report-footnote">This is an automated document check against SICTIC Investor Day criteria.
    It is not a jury decision and does not submit an application.</p>
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
) -> bytes:
    """Return PDF bytes using Chromium print (same idea as browser Print)."""
    document = build_report_document_html(
        deck_filename=deck_filename,
        report_body_html=report_body_html,
        logo=logo,
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

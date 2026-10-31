from __future__ import annotations

import pytest

from spike import report_pdf


def test_build_report_document_html_includes_masthead_and_body():
    html = report_pdf.build_report_document_html(
        deck_filename="deck.pdf",
        report_body_html="<table><tr><td>Fine</td></tr></table>",
    )
    assert "Review of deck.pdf" in html
    assert "SICTIC pitch deck review" in html
    assert "<table><tr><td>Fine</td></tr></table>" in html
    assert "A4 landscape" in html
    assert 'src="data:image/svg+xml;base64,' in html
    assert "file://" not in html


def test_logo_data_uri_reads_svg(tmp_path):
    logo = tmp_path / "mark.svg"
    logo.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    uri = report_pdf.logo_data_uri(logo)
    assert uri is not None
    assert uri.startswith("data:image/svg+xml;base64,")


def test_normalize_report_body_html_restores_breaks():
    assert (
        report_pdf.normalize_report_body_html("a&lt;br&gt;b&lt;br/&gt;c")
        == "a<br>b<br>c"
    )


def test_render_report_pdf_prefers_playwright(mocker):
    mocker.patch(
        "spike.report_pdf._pdf_via_playwright",
        return_value=b"%PDF-1.4 chrome",
    )
    weasy = mocker.patch("spike.report_pdf._pdf_via_weasyprint")

    pdf = report_pdf.render_report_pdf(
        deck_filename="deck.pdf",
        report_body_html="<p>ok</p>",
    )

    assert pdf.startswith(b"%PDF")
    weasy.assert_not_called()


def test_render_report_pdf_falls_back_to_weasyprint(mocker):
    mocker.patch(
        "spike.report_pdf._pdf_via_playwright",
        side_effect=RuntimeError("no browser"),
    )
    mocker.patch(
        "spike.report_pdf._pdf_via_weasyprint",
        return_value=b"%PDF-1.4 weasy",
    )

    pdf = report_pdf.render_report_pdf(
        deck_filename="deck.pdf",
        report_body_html="<p>ok</p>",
    )

    assert pdf == b"%PDF-1.4 weasy"


def test_render_report_pdf_raises_when_both_engines_fail(mocker):
    mocker.patch(
        "spike.report_pdf._pdf_via_playwright",
        side_effect=RuntimeError("no browser"),
    )
    mocker.patch(
        "spike.report_pdf._pdf_via_weasyprint",
        side_effect=RuntimeError("no weasy"),
    )
    with pytest.raises(RuntimeError, match="PDF generation failed"):
        report_pdf.render_report_pdf(
            deck_filename="deck.pdf",
            report_body_html="<p>ok</p>",
        )

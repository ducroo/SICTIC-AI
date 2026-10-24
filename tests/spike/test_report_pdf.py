from __future__ import annotations

import pytest

from spike import report_pdf


def test_build_report_document_html_includes_masthead_and_body():
    html = report_pdf.build_report_document_html(
        deck_filename="deck.pdf",
        report_body_html="<table><tr><td>Fine</td></tr></table>",
        logo=None,
    )
    assert "Review of deck.pdf" in html
    assert "SICTIC pitch deck review" in html
    assert "<table><tr><td>Fine</td></tr></table>" in html
    assert "A4 landscape" in html


def test_render_report_pdf_uses_weasyprint(mocker):
    fake_html = mocker.Mock()
    fake_html.write_pdf.return_value = b"%PDF-1.4 fake"
    html_cls = mocker.patch("weasyprint.HTML", return_value=fake_html)

    pdf = report_pdf.render_report_pdf(
        deck_filename="deck.pdf",
        report_body_html="<p>ok</p>",
    )

    assert pdf.startswith(b"%PDF")
    html_cls.assert_called_once()
    fake_html.write_pdf.assert_called_once()


def test_render_report_pdf_requires_weasyprint(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(RuntimeError, match="WeasyPrint is not installed"):
        report_pdf.render_report_pdf(
            deck_filename="deck.pdf",
            report_body_html="<p>ok</p>",
        )

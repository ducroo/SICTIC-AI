from __future__ import annotations

from pathlib import Path

import pytest

from spike import email_report


def test_email_reports_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SPIKE_EMAIL_REPORTS", raising=False)
    assert email_report.email_reports_enabled() is False


def test_email_reports_enabled_flag(monkeypatch):
    monkeypatch.setenv("SPIKE_EMAIL_REPORTS", "1")
    assert email_report.email_reports_enabled() is True


def test_build_report_email_html_is_short_and_points_to_attachment():
    html = email_report.build_report_email_html(
        deck_filename="deck.pdf",
        report_markdown="# unused",
        report_html="<table><tr><td>Fine</td></tr></table>",
    )
    assert "Review of deck.pdf" in html
    assert "PDF report is attached" in html
    assert "<table>" not in html


def test_send_report_email_requires_enabled(monkeypatch):
    monkeypatch.delenv("SPIKE_EMAIL_REPORTS", raising=False)
    with pytest.raises(RuntimeError, match="SPIKE_EMAIL_REPORTS"):
        email_report.send_report_email(
            to_email="urs@gubser.ch",
            deck_filename="deck.pdf",
            report_markdown="# Report",
            report_html="<p>ok</p>",
        )


def test_send_report_email_invokes_gws(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_EMAIL_REPORTS", "1")
    monkeypatch.setenv("SPIKE_GWS_BIN", "/usr/bin/gws")
    completed = mocker.Mock(returncode=0, stdout="{}", stderr="")
    run = mocker.patch("lib.infrastructure.gmail.subprocess.run", return_value=completed)

    email_report.send_report_email(
        to_email="urs@gubser.ch",
        deck_filename="deck.pdf",
        report_markdown="# Report",
        report_html="<p>ok</p>",
        pdf_bytes=b"%PDF-1.4",
    )

    command = run.call_args.args[0]
    assert command[0] == "/usr/bin/gws"
    assert command[1:3] == ["gmail", "+send"]
    assert "--to" in command and "urs@gubser.ch" in command
    assert "--html" in command
    assert "--attach" in command
    assert command[command.index("--attach") + 1].endswith("-sictic-review.pdf")
    assert "/" not in command[command.index("--attach") + 1]
    assert run.call_args.kwargs["check"] is False
    assert Path(run.call_args.kwargs["cwd"]).name.startswith("spike-email-")


def test_send_report_email_surfaces_gws_failure(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_EMAIL_REPORTS", "1")
    mocker.patch(
        "lib.infrastructure.gmail.subprocess.run",
        return_value=mocker.Mock(returncode=2, stdout="", stderr="auth missing"),
    )
    with pytest.raises(RuntimeError, match="gws gmail \\+send failed"):
        email_report.send_report_email(
            to_email="urs@gubser.ch",
            deck_filename="deck.pdf",
            report_markdown="# Report",
            report_html="<p>ok</p>",
        )

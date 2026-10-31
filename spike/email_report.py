"""Send completed pitch-deck reports through the Google Workspace CLI (`gws`)."""

from __future__ import annotations

import os
from pathlib import Path

from lib.infrastructure.gmail import send_html_email

DEFAULT_SUBJECT_PREFIX = "SICTIC pitch deck review"


def email_reports_enabled() -> bool:
    flag = (os.environ.get("SPIKE_EMAIL_REPORTS") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def build_report_email_html(*, deck_filename: str, report_markdown: str, report_html: str) -> str:
    """Short HTML body; the full report is the attached PDF."""
    del report_markdown, report_html  # kept for call-site compatibility
    title = f"Review of {deck_filename}"
    return (
        f"<h1>{title}</h1>"
        "<p>Your SICTIC pitch deck review is ready. The PDF report is attached.</p>"
    )


def send_report_email(
    *,
    to_email: str,
    deck_filename: str,
    report_markdown: str,
    report_html: str,
    pdf_bytes: bytes | None = None,
    subject: str | None = None,
) -> None:
    """Send one report email via `gws gmail +send`. Raises on failure."""
    recipient = (to_email or "").strip()
    if not recipient or "@" not in recipient:
        raise ValueError("A valid recipient email is required.")
    if not email_reports_enabled():
        raise RuntimeError("SPIKE_EMAIL_REPORTS is not enabled.")

    mail_subject = subject or f"{DEFAULT_SUBJECT_PREFIX}: {deck_filename}"
    html = build_report_email_html(
        deck_filename=deck_filename,
        report_markdown=report_markdown,
        report_html=report_html,
    )
    safe_stem = "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in Path(deck_filename).stem
    ).strip("._") or "pitch-deck"
    attach_name = f"{safe_stem}-sictic-review.pdf"
    send_html_email(
        [recipient],
        mail_subject,
        html,
        attachments={attach_name: pdf_bytes} if pdf_bytes else None,
        gws=os.environ.get("SPIKE_GWS_BIN"),
        temp_prefix="spike-email-",
    )

"""Send Markdown content as a styled HTML email through gws."""

from __future__ import annotations

from lib.infrastructure.gmail import send_html_email
from skills.send_gmail.render_email import markdown_to_email


def send_gmail(markdown: str, recipients: list[str], subject: str) -> None:
    """Send the complete Markdown content in the body of one email.

    Raises InfrastructureError when gws fails. A failed send may still have
    been delivered, so callers must not retry it automatically.
    """
    if not subject.strip():
        raise ValueError("An email subject is required.")
    send_html_email(recipients, subject.strip(), markdown_to_email(markdown))

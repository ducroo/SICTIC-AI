"""Send completed pitch-deck reports through the Google Workspace CLI (`gws`)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SUBJECT_PREFIX = "SICTIC pitch deck review"


def email_reports_enabled() -> bool:
    flag = (os.environ.get("SPIKE_EMAIL_REPORTS") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def gws_binary() -> str:
    configured = (os.environ.get("SPIKE_GWS_BIN") or "").strip()
    if configured:
        return configured
    found = shutil.which("gws")
    if found:
        return found
    home_bin = Path.home() / "bin" / "gws"
    if home_bin.is_file():
        return str(home_bin)
    return "gws"


def build_report_email_html(*, deck_filename: str, report_markdown: str, report_html: str) -> str:
    """Build an HTML fragment for `gws gmail +send --html`."""
    title = f"Review of {deck_filename}"
    body = report_html.strip() or f"<pre>{report_markdown}</pre>"
    return (
        f"<h1>{title}</h1>"
        "<p>Your SICTIC pitch deck review is ready. "
        "This is an automated document check. It is not a jury decision "
        "and does not submit an application.</p>"
        f"{body}"
        '<p style="color:#607382;font-size:0.9rem">'
        "Sent from the SICTIC pitch deck review service."
        "</p>"
    )


def send_report_email(
    *,
    to_email: str,
    deck_filename: str,
    report_markdown: str,
    report_html: str,
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
    gws = gws_binary()
    env = os.environ.copy()
    # Prefer an explicit credentials file when set (headless / VPS export flow).
    creds = (os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE") or "").strip()
    if creds:
        env["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = creds
    env.setdefault("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND", "file")

    with tempfile.TemporaryDirectory(prefix="spike-email-") as tmp:
        body_path = Path(tmp) / "body.html"
        body_path.write_text(html, encoding="utf-8")
        command = [
            gws,
            "gmail",
            "+send",
            "--to",
            recipient,
            "--subject",
            mail_subject,
            "--html",
            "--body",
            body_path.read_text(encoding="utf-8"),
        ]
        logger.info("Sending review email to %s via %s", recipient, gws)
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"gws gmail +send failed (exit {completed.returncode}): {detail[:800]}"
        )
    logger.info("Review email accepted by gws for %s", recipient)

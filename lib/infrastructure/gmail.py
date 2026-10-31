"""Send email through the Google Workspace CLI (`gws`)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Seconds to wait for `gws` to accept the message.
SEND_TIMEOUT_SECONDS = 180


def gws_binary(configured: str | None = None) -> str:
    """Return the `gws` program: the configured path, then PATH, then ~/bin/gws."""
    configured = (configured or "").strip()
    if configured:
        return configured
    found = shutil.which("gws")
    if found:
        return found
    home_bin = Path.home() / "bin" / "gws"
    if home_bin.is_file():
        return str(home_bin)
    return "gws"


def _send_error(
    message: str,
    kind: InfrastructureErrorKind,
) -> InfrastructureError:
    # A failed or timed-out send may still have been delivered; never retry it automatically.
    return InfrastructureError(
        message,
        kind=kind,
        provider="gws",
        operation="send_email",
        recoverable=False,
    )


def send_html_email(
    recipients: list[str],
    subject: str,
    html: str,
    *,
    attachments: dict[str, bytes] | None = None,
    gws: str | None = None,
    temp_prefix: str = "gws-email-",
) -> None:
    """Send one HTML email to all recipients with `gws gmail +send`.

    `attachments` maps file names to their content. `gws` only attaches files
    below its working directory, so the send runs in a temporary directory
    below the current one. Raises InfrastructureError when `gws` fails.
    """
    addresses = [address.strip() for address in recipients if address.strip()]
    if not addresses or any("@" not in address for address in addresses):
        raise ValueError("Valid recipient email addresses are required.")
    program = gws_binary(gws)
    env = os.environ.copy()
    env.setdefault("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND", "file")

    with tempfile.TemporaryDirectory(prefix=temp_prefix, dir=".") as temporary:
        temporary_path = Path(temporary)
        command = [
            program,
            "gmail",
            "+send",
            "--to",
            ",".join(addresses),
            "--subject",
            subject,
            "--html",
            "--body",
            html,
        ]
        for filename, content in (attachments or {}).items():
            (temporary_path / filename).write_bytes(content)
            command.extend(["--attach", filename])
        logger.info(
            "Sending email to %s via %s (attachments=%d)",
            ", ".join(addresses),
            program,
            len(attachments or {}),
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(temporary_path),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as error:
            raise _send_error(
                f"gws program not found: {program}",
                InfrastructureErrorKind.CONFIGURATION,
            ) from error
        except subprocess.TimeoutExpired as error:
            raise _send_error(
                f"gws gmail +send did not finish within {SEND_TIMEOUT_SECONDS} seconds",
                InfrastructureErrorKind.TIMEOUT,
            ) from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise _send_error(
            f"gws gmail +send failed (exit {completed.returncode}): {detail[:800]}",
            InfrastructureErrorKind.SERVICE_UNAVAILABLE,
        )
    logger.info("Email accepted by gws for %s", ", ".join(addresses))

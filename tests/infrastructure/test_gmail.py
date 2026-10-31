import subprocess
from pathlib import Path

import pytest

from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.gmail import send_html_email


def test_send_html_email_sends_one_email_to_all_recipients(mocker):
    completed = mocker.Mock(returncode=0, stdout="{}", stderr="")
    run = mocker.patch("lib.infrastructure.gmail.subprocess.run", return_value=completed)

    send_html_email(
        ["a@sictic.ch", " b@sictic.ch "],
        "Subject line",
        "<p>Body</p>",
        attachments={"report.pdf": b"%PDF-1.4"},
        gws="/usr/bin/gws",
    )

    command = run.call_args.args[0]
    assert command[:3] == ["/usr/bin/gws", "gmail", "+send"]
    assert command[command.index("--to") + 1] == "a@sictic.ch,b@sictic.ch"
    assert command[command.index("--subject") + 1] == "Subject line"
    assert command[command.index("--body") + 1] == "<p>Body</p>"
    assert "--html" in command
    assert command[command.index("--attach") + 1] == "report.pdf"
    assert run.call_args.kwargs["check"] is False
    assert Path(run.call_args.kwargs["cwd"]).name.startswith("gws-email-")


def test_send_html_email_requires_valid_recipients():
    with pytest.raises(ValueError, match="recipient"):
        send_html_email([" "], "Subject", "<p>Body</p>")
    with pytest.raises(ValueError, match="recipient"):
        send_html_email(["not-an-address"], "Subject", "<p>Body</p>")


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        ("exit", InfrastructureErrorKind.SERVICE_UNAVAILABLE),
        ("missing", InfrastructureErrorKind.CONFIGURATION),
        ("timeout", InfrastructureErrorKind.TIMEOUT),
    ],
)
def test_send_html_email_failures_are_not_retried(mocker, failure, kind):
    run = mocker.patch("lib.infrastructure.gmail.subprocess.run")
    if failure == "exit":
        run.return_value = mocker.Mock(returncode=2, stdout="", stderr="auth missing")
    elif failure == "missing":
        run.side_effect = FileNotFoundError("gws")
    else:
        run.side_effect = subprocess.TimeoutExpired("gws", 180)

    with pytest.raises(InfrastructureError) as error:
        send_html_email(["a@sictic.ch"], "Subject", "<p>Body</p>", gws="gws")

    assert error.value.kind == kind
    assert error.value.provider == "gws"
    # A failed send may still have been delivered.
    assert error.value.recoverable is False
    if failure == "exit":
        assert "gws gmail +send failed (exit 2): auth missing" in str(error.value)

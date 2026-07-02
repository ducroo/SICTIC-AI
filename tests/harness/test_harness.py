import pytest

from skills.harness.harness import HarnessCommand, dispatch_command, help_text


@pytest.mark.asyncio
async def test_harness_dispatches_registered_command():
    async def handler(args):
        return " ".join(args)

    registry = {
        "/echo": HarnessCommand("/echo", "/echo <text>", "Echo text.", handler)
    }

    result = await dispatch_command('/echo hello "world again"', registry)

    assert result == "hello world again"


@pytest.mark.asyncio
async def test_harness_unknown_command_is_readable():
    result = await dispatch_command("/missing")

    assert "Unknown command" in result
    assert "/help" in result


@pytest.mark.asyncio
async def test_harness_non_slash_input_is_rejected():
    result = await dispatch_command("profile avientus")

    assert "Use slash commands" in result


def test_harness_help_lists_core_commands():
    text = help_text()

    assert "/dataset_chat <dataset> <question>" in text
    assert "/startup_profile <startup>" in text
    assert "/dd_checks <startup>" in text
    assert "/dealum_import <startup>" in text


def test_harness_cli_accepts_one_shot_command():
    from typer.testing import CliRunner
    from skills.harness.__main__ import app

    result = CliRunner().invoke(app, ["/help"])

    assert result.exit_code == 0
    assert "Available commands" in result.output


def test_harness_cli_rejects_interactive_mode_without_tty():
    from typer.testing import CliRunner
    from skills.harness.__main__ import app

    result = CliRunner().invoke(app, [])

    assert result.exit_code == 2
    assert "--no-capture-output" in result.output

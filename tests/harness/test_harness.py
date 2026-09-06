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
async def test_harness_apostrophe_in_query_is_not_a_parse_error():
    async def handler(args):
        return " ".join(args)

    registry = {
        "/echo": HarnessCommand("/echo", "/echo <text>", "Echo text.", handler)
    }

    result = await dispatch_command("/echo What's the funding ask?", registry)

    assert "Parse error" not in result
    assert result == "What's the funding ask?"


@pytest.mark.asyncio
async def test_harness_double_quotes_group_strip_and_keep_apostrophe():
    async def handler(args):
        return f"{len(args)}|" + "|".join(args)

    registry = {
        "/echo": HarnessCommand("/echo", "/echo <text>", "Echo text.", handler)
    }

    result = await dispatch_command('/echo "What\'s the funding ask?"', registry)

    assert result == "1|What's the funding ask?"


@pytest.mark.asyncio
async def test_harness_empty_input_returns_empty_string():
    result = await dispatch_command("   ")

    assert result == ""


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
    assert "/submission_ready [startup ...]" in text
    assert "/dd_checks <startup>" in text
    assert "/dd_priorities <startup>" in text
    assert "/sha_review <dataset>" in text
    assert "/dealum_import <startup>" in text


def test_harness_cli_accepts_one_shot_command():
    from typer.testing import CliRunner
    from skills.harness.__main__ import app

    result = CliRunner().invoke(app, ["/help"])

    assert result.exit_code == 0
    assert "Available commands" in result.output


@pytest.mark.parametrize("whole_command", [False, True])
def test_harness_cli_preserves_multiword_dataset_and_person(monkeypatch, whole_command):
    from importlib import import_module
    from unittest.mock import AsyncMock
    from typer.testing import CliRunner
    from skills.harness.__main__ import app

    profile = AsyncMock(return_value=[])
    monkeypatch.setattr(import_module("skills.person_profile.person_profile"), "person_profile", profile)
    arguments = (
        ['/person_profile "Example Startup" "Jane Founder"']
        if whole_command else ["/person_profile", "Example Startup", "Jane Founder"]
    )
    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == 0, result.output
    profile.assert_awaited_once_with("Example Startup", "Jane Founder")


def test_harness_cli_preserves_literal_argument_content(monkeypatch):
    from importlib import import_module
    from unittest.mock import AsyncMock
    from typer.testing import CliRunner
    from skills.harness.__main__ import app

    advocates = AsyncMock(return_value=[])
    monkeypatch.setattr(import_module("skills.advocates.advocates"), "advocates", advocates)
    description = 'What\'s "new"? Café partners; C:\\notes\\panel'
    result = CliRunner().invoke(
        app, ["--", "/advocates", "Founders' Forum", "--description", description],
    )

    assert result.exit_code == 0, result.output
    advocates.assert_awaited_once_with("Founders' Forum", description)


def test_harness_cli_rejects_interactive_mode_without_tty():
    from typer.testing import CliRunner
    from skills.harness.__main__ import app

    result = CliRunner().invoke(app, [])

    assert result.exit_code == 2
    assert "--no-capture-output" in result.output

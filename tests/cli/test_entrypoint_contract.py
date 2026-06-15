from __future__ import annotations

import importlib

import pytest
import typer
from typer.testing import CliRunner

from lib.cli import run_command


class _Logger:
    def __init__(self):
        self.messages: list[str] = []

    def error(self, message: str) -> None:
        self.messages.append(message)


def test_run_command_supports_sync_and_async_actions():
    async def async_action():
        return "async"

    logger = _Logger()

    assert run_command(lambda: "sync", logger=logger) == "sync"
    assert run_command(async_action, logger=logger) == "async"
    assert logger.messages == []


def test_run_command_reports_errors_consistently(capsys):
    logger = _Logger()

    with pytest.raises(typer.Exit) as raised:
        run_command(
            lambda: (_ for _ in ()).throw(ValueError("bad input")),
            logger=logger,
            error_prefix="Execution failed",
        )

    assert raised.value.exit_code == 1
    assert logger.messages == ["Execution failed: bad input"]
    assert "Execution failed: bad input" in capsys.readouterr().err


@pytest.mark.parametrize(
    "module_name",
    [
        "skills.advocates.__main__",
        "skills.batch_audit.__main__",
        "skills.bulk_refresh.__main__",
        "skills.config_load.__main__",
        "skills.dataset_chat.__main__",
        "skills.dataset_maintenance.__main__",
        "skills.dd_checks.__main__",
        "skills.dealum_import.__main__",
        "skills.expert_search.__main__",
        "skills.gdrive_sync.__main__",
        "skills.harness.__main__",
        "skills.investor_profile.__main__",
        "skills.linkedin_maintenance.__main__",
        "skills.llm_chat.__main__",
        "skills.person_profile.__main__",
        "skills.potential_investors.__main__",
        "skills.ranking.__main__",
        "skills.sictic_git_sync.__main__",
        "skills.startup_profile.__main__",
        "skills.startup_traction.__main__",
        "skills.suggested_startups.__main__",
        "skills.team_profile.__main__",
    ],
)
def test_typer_entrypoint_renders_help(module_name):
    module = importlib.import_module(module_name)

    result = CliRunner().invoke(module.app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output

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
        "skills.submission_ready.__main__",
        "skills.dataset_chat.__main__",
        "skills.dataset_maintenance.__main__",
        "skills.dd_checks.__main__",
        "skills.dd_priorities.__main__",
        "skills.dealum_import.__main__",
        "skills.expert_search.__main__",
        "skills.harness.__main__",
        "skills.investor_profile.__main__",
        "skills.linkedin_maintenance.__main__",
        "skills.llm_chat.__main__",
        "skills.person_profile.__main__",
        "skills.potential_investors.__main__",
        "skills.ranking.__main__",
        "skills.startup_profile.__main__",
        "skills.startup_traction.__main__",
        "skills.startup_website_import.__main__",
        "skills.suggested_startups.__main__",
        "skills.team_profile.__main__",
    ],
)
def test_typer_entrypoint_renders_help(module_name):
    module = importlib.import_module(module_name)

    result = CliRunner().invoke(module.app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_person_profile_cli_accepts_comma_separated_people(monkeypatch):
    module = importlib.import_module("skills.person_profile.__main__")
    captured = {}

    async def fake_person_profile(*, dataset_name, names):
        captured["dataset_name"] = dataset_name
        captured["names"] = names
        return []

    monkeypatch.setattr(module, "person_profile", fake_person_profile)

    result = CliRunner().invoke(
        module.app,
        [
            "--dataset",
            "sictic-members",
            "--person",
            "Thomas Dübendorfer, , Bolko Hohaus",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "dataset_name": "sictic-members",
        "names": ["Thomas Dübendorfer", "Bolko Hohaus"],
    }


def test_suggested_startups_cli_accepts_comma_separated_investors(monkeypatch):
    module = importlib.import_module("skills.suggested_startups.__main__")
    captured = {}

    async def fake_suggested_startups(*, startups, investors, max_startups):
        captured["startups"] = startups
        captured["investors"] = investors
        captured["max_startups"] = max_startups
        return []

    monkeypatch.setattr(
        module,
        "suggested_startups",
        fake_suggested_startups,
    )

    result = CliRunner().invoke(
        module.app,
        [
            "--investor",
            "Lucas du Croo de Jongh, , Bolko Hohaus",
            "--max-startups",
            "10",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "startups": None,
        "investors": ["Lucas du Croo de Jongh", "Bolko Hohaus"],
        "max_startups": 10,
    }


def test_startup_profile_cli_accepts_comma_separated_startups(monkeypatch):
    module = importlib.import_module("skills.startup_profile.__main__")
    captured = []

    async def fake_startup_profile(startup, files):
        captured.append((startup, files))
        return []

    monkeypatch.setattr(module, "startup_profile", fake_startup_profile)

    result = CliRunner().invoke(
        module.app,
        ["--startup", "Avientus, , DAAV"],
    )

    assert result.exit_code == 0
    assert captured == [("Avientus", None), ("DAAV", None)]


def test_startup_profile_cli_continues_after_startup_failure(monkeypatch):
    module = importlib.import_module("skills.startup_profile.__main__")
    captured = []

    async def fake_startup_profile(startup, files):
        captured.append((startup, files))
        if startup == "Scanvio":
            raise RuntimeError("dataset sync timed out")
        return []

    monkeypatch.setattr(module, "startup_profile", fake_startup_profile)

    result = CliRunner().invoke(
        module.app,
        ["--startup", "Scanvio, Unisers"],
    )

    assert captured == [("Scanvio", None), ("Unisers", None)]
    assert result.exit_code == 1
    assert "Failed startups:" in result.output
    assert "Scanvio: dataset sync timed out" in result.output

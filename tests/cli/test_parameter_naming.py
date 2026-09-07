"""Canonical CLI names and legacy aliases preserve workflow inputs."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from skills.harness.harness import dispatch_command, help_text


@pytest.mark.parametrize("legacy", [False, True], ids=["canonical", "legacy"])
@pytest.mark.parametrize(
    "skill,canonical,old,expected_args,expected_kwargs",
    [
        (
            "investor_profile",
            ["--dataset", "members", "--persons", "Jane Doe, John Doe"],
            ["--source-dataset", "members", "--person", "Jane Doe, John Doe"],
            (),
            {"source_dataset": "members", "names": ["Jane Doe", "John Doe"]},
        ),
        (
            "person_profile",
            ["--dataset", "members", "--persons", "Jane Doe, John Doe"],
            ["--dataset", "members", "--person", "Jane Doe, John Doe"],
            (),
            {"dataset_name": "members", "names": ["Jane Doe", "John Doe"]},
        ),
        (
            "suggested_startups",
            ["--investors", "Jane Doe, John Doe", "--startups", "a", "--startups", "b"],
            ["--investor", "Jane Doe, John Doe", "--startups", "a", "--startups", "b"],
            (),
            {"startups": ["a", "b"], "investors": ["Jane Doe", "John Doe"], "max_startups": 16},
        ),
        (
            "submission_ready",
            ["--startups", "Example One", "--startups", "Example Two"],
            ["--startup", "Example One", "--startup", "Example Two"],
            (["Example One", "Example Two"],),
            {},
        ),
        ("team_profile_revised", ["--startup", "Example One"], ["--dataset", "Example One"], ("Example One",), {}),
        ("sha_review", ["--startup", "Example One"], ["--dataset", "Example One"], ("Example One",), {}),
    ],
)
def test_selectors_preserve_python_calls(
    monkeypatch, legacy, skill, canonical, old, expected_args, expected_kwargs,
):
    module = importlib.import_module(f"skills.{skill}.__main__")
    workflow = AsyncMock(return_value=[])
    monkeypatch.setattr(module, skill, workflow)

    result = CliRunner().invoke(module.app, old if legacy else canonical)

    assert result.exit_code == 0, result.output
    workflow.assert_awaited_once_with(*expected_args, **expected_kwargs)


@pytest.mark.parametrize("option", ["--startups", "--startup"])
def test_startup_profile_batch_keeps_files_order_and_failure_behavior(monkeypatch, option):
    module = importlib.import_module("skills.startup_profile.__main__")
    workflow = AsyncMock(side_effect=[RuntimeError("fixture failure"), []])
    monkeypatch.setattr(module, "startup_profile", workflow)

    result = CliRunner().invoke(
        module.app,
        [option, "Example One, , Example Two", "--files", "one.pdf", "--files", "two.pdf"],
    )

    assert result.exit_code == 1
    assert "fixture failure" in result.output
    assert [call.args for call in workflow.await_args_list] == [
        ("Example One", ["one.pdf", "two.pdf"]),
        ("Example Two", ["one.pdf", "two.pdf"]),
    ]


@pytest.mark.parametrize("option", ["--datasets", "--dataset"])
@pytest.mark.parametrize(
    "command,operation",
    [("activate", "activate_dataset_marker"), ("archive", "archive_dataset_marker"), ("rebuild-index", "rebuild_dataset_index")],
)
def test_maintenance_batch_selectors_keep_scope_and_sync(monkeypatch, option, command, operation):
    module = importlib.import_module("skills.dataset_maintenance.__main__")
    workflow = Mock(side_effect=lambda dataset: SimpleNamespace(
        dataset=dataset, collection="fixture", collection_deleted=True, documents_reset=2,
    ))
    sync = AsyncMock(return_value=[])
    monkeypatch.setattr(module, operation, workflow)
    monkeypatch.setattr(module, "sync_datasets", sync)

    result = CliRunner().invoke(module.app, [command, option, "a, , b"])

    assert result.exit_code == 0, result.output
    assert [call.args for call in workflow.call_args_list] == [("a",), ("b",)]
    if command == "rebuild-index":
        sync.assert_awaited_once_with(["a", "b"], raise_on_error=True)
    else:
        sync.assert_not_awaited()


@pytest.mark.parametrize("option", ["--source-datasets", "--source-dataset"])
def test_source_and_target_roles_remain_distinct(monkeypatch, option):
    module = importlib.import_module("skills.dataset_maintenance.__main__")
    workflow = AsyncMock(return_value=[])
    monkeypatch.setattr(module, "dataset_from_insight", workflow)

    result = CliRunner().invoke(module.app, [
        "dataset-from-insight", "--target-dataset", "output",
        option, "a,b", "--skill", "person_profile", "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    workflow.assert_awaited_once_with("output", ["a", "b"], "person_profile", dry_run=True)


def test_delete_remains_a_single_dataset_operation(monkeypatch):
    module = importlib.import_module("skills.dataset_maintenance.__main__")
    workflow = Mock(return_value=[])
    monkeypatch.setattr(module, "delete_dataset_index", workflow)

    result = CliRunner().invoke(module.app, ["delete", "--dataset", "a"])
    assert result.exit_code == 0, result.output
    workflow.assert_called_once_with("a", None)
    workflow.reset_mock()

    result = CliRunner().invoke(module.app, ["delete", "--datasets", "a,b"])
    assert result.exit_code == 2
    workflow.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["--dataset", "--source-dataset"])
async def test_harness_investor_dataset_aliases(monkeypatch, option):
    module = importlib.import_module("skills.investor_profile.investor_profile")
    workflow = AsyncMock(return_value=[])
    monkeypatch.setattr(module, "investor_profile", workflow)

    await dispatch_command(["/investor_profile", option, "Example Members"])

    workflow.assert_awaited_once_with(source_dataset="Example Members")


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["--investors", "--investor"])
async def test_harness_investor_list_aliases(monkeypatch, option):
    module = importlib.import_module("skills.suggested_startups.suggested_startups")
    workflow = AsyncMock(return_value=[])
    monkeypatch.setattr(module, "suggested_startups", workflow)

    await dispatch_command([
        "/suggested_startups", "--startups", "a,b", option, "Jane Doe, John Doe",
    ])

    workflow.assert_awaited_once_with(
        startups=["a", "b"], investors=["Jane Doe", "John Doe"], max_startups=16,
    )


@pytest.mark.parametrize(
    "skill,subcommand,argument,metavar",
    [
        ("dealum_import", None, "startup", "STARTUPS"),
        ("startup_website_import", None, "startup_name", "STARTUP"),
        ("dataset_maintenance", "create", "startup_name", "STARTUP"),
        ("dataset_chat", "search", "dataset_name", "DATASET"),
        ("dataset_chat", "chat", "dataset_name", "DATASET"),
        ("dataset_chat", "chat", "questions", "QUESTION"),
        ("dataset_chat", "sync", "dataset_names", "DATASETS..."),
    ],
)
def test_positional_labels_express_subject_and_cardinality(skill, subcommand, argument, metavar):
    module = importlib.import_module(f"skills.{skill}.__main__")
    command = get_command(module.app)
    if subcommand:
        command = command.commands[subcommand]
    parameter = next(item for item in command.params if item.name == argument)
    assert parameter.metavar == metavar


def test_harness_help_advertises_canonical_selectors():
    text = help_text()
    assert "/investor_profile [--dataset dataset]" in text
    assert "--investors x,y" in text
    assert "/sha_review <startup>" in text
    assert "/submission_ready [startups ...]" in text
    assert "--source-dataset" not in text
    assert "--investor " not in text

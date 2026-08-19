import pytest
import importlib.util
import sys
from pathlib import Path

from typer.testing import CliRunner

from lib.insights import (
    InsightFile,
    dataset_from_insight,
    select_insights,
)
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_select_insights_does_not_materialize_dataset(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("sictic-members", "community")
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/"
        "urs-gubser-gpt-5-4-mini.md",
        "preferred profile",
    )

    selected = select_insights(["sictic-members"], "person_profile")

    assert len(selected) == 1
    assert selected[0].identifier == "urs-gubser"
    assert not storage.exists("storage/generated/sictic-members-person-profile")


def _create_dataset(name: str, domain: str):
    location = dataset_location_for_domain(name, domain)
    get_storage().mkdir(location.raw_rel)
    return location


def _load_script(name: str):
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    path = REPO_ROOT / "scripts" / f"{name}.py"
    module_name = f"_test_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_dataset_from_insight_selects_ranked_profile_and_removes_stale_file(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini,ollama/qwen3:8b")
    storage = get_storage()
    _create_dataset("sictic-members", "community")

    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/urs-gubser-qwen3-8b.md",
        "old qwen profile",
    )
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/urs-gubser-gpt-5-4-mini.md",
        "preferred gpt profile",
    )
    storage.write_text(
        "storage/generated/sictic-members-person-profile/datasets/"
        "sictic-members/insights/person-profile/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    selected = await dataset_from_insight(
        "sictic-members-person-profile",
        ["sictic-members"],
        "person_profile",
    )

    assert [insight.model for insight in selected] == ["ollama/gpt-5.4-mini"]
    target = (
        "storage/generated/sictic-members-person-profile/datasets/"
        "sictic-members/insights/person-profile/"
    )
    assert storage.exists(f"{target}urs-gubser-gpt-5-4-mini.md")
    assert not storage.exists(f"{target}urs-gubser-qwen3-8b.md")
    assert storage.read_text(
        f"{target}urs-gubser-gpt-5-4-mini.md"
    ) == "preferred gpt profile"


@pytest.mark.asyncio
async def test_dataset_from_insight_selects_manual_root_insight(mock_env):
    storage = get_storage()
    _create_dataset("avientus", "startups")
    storage.write_text(
        "storage/startups/avientus/insights/"
        "persons-in-dataset-avientus-manual.md",
        "manual persons",
    )

    selected = await dataset_from_insight(
        "avientus-persons-in-dataset",
        ["avientus"],
        "persons_in_dataset",
    )

    assert len(selected) == 1
    assert storage.read_text(
        "storage/generated/avientus-persons-in-dataset/datasets/"
        "avientus/insights/persons-in-dataset-avientus-manual.md"
    ) == "manual persons"


@pytest.mark.asyncio
async def test_dataset_from_insight_dry_run_does_not_write_or_remove(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("sictic-members", "community")

    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/urs-gubser-gpt-5-4-mini.md",
        "preferred gpt profile",
    )
    storage.write_text(
        "storage/generated/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    selected = await dataset_from_insight(
        "sictic-members-person-profile",
        ["sictic-members"],
        "person_profile",
        dry_run=True,
    )

    assert len(selected) == 1
    assert not storage.exists(
        "storage/generated/sictic-members-person-profile/datasets/"
        "sictic-members/insights/person-profile/urs-gubser-gpt-5-4-mini.md"
    )
    assert storage.exists("storage/generated/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md")


@pytest.mark.asyncio
async def test_dataset_from_insight_without_sources_scans_all_datasets(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("avientus", "startups")
    _create_dataset("archived", "startups")
    storage.write_text(
        "storage/startups/avientus/insights/person-profile/jane-doe-gpt-5-4-mini.md",
        "active profile",
    )
    storage.write_text(
        "storage/startups/archived/insights/person-profile/john-doe-gpt-5-4-mini.md",
        "archived profile",
    )

    selected = await dataset_from_insight(
        "all-person-profile",
        None,
        "person_profile",
    )

    assert {insight.dataset for insight in selected} == {"avientus", "archived"}
    target = "storage/generated/all-person-profile/datasets"
    assert storage.exists(
        f"{target}/avientus/insights/person-profile/"
        "jane-doe-gpt-5-4-mini.md"
    )
    assert storage.exists(
        f"{target}/archived/insights/person-profile/"
        "john-doe-gpt-5-4-mini.md"
    )


@pytest.mark.asyncio
async def test_dataset_from_insight_copies_only_when_source_is_newer(
    mock_env,
    monkeypatch,
):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("avientus", "startups")
    source = (
        "storage/startups/avientus/insights/"
        "startup-profile-avientus-gpt-5-4-mini.md"
    )
    target = (
        "storage/generated/avientus-startup-profile/datasets/avientus/"
        "insights/startup-profile-avientus-gpt-5-4-mini.md"
    )
    storage.write_text(source, "new source")
    storage.set_mtime(source, 200)
    storage.write_text(target, "old target")
    storage.set_mtime(target, 100)

    await dataset_from_insight(
        "avientus-startup-profile",
        ["avientus"],
        "startup_profile",
    )
    assert storage.read_text(target) == "new source"

    storage.write_text(target, "newer target")
    storage.set_mtime(target, 300)
    await dataset_from_insight(
        "avientus-startup-profile",
        ["avientus"],
        "startup_profile",
    )
    assert storage.read_text(target) == "newer target"


@pytest.mark.asyncio
async def test_dataset_from_insight_empty_sources_remove_outdated_files(mock_env):
    storage = get_storage()
    obsolete = (
        "storage/generated/selected-person-profile/datasets/avientus/"
        "insights/person-profile/obsolete-manual.md"
    )
    storage.write_text(obsolete, "obsolete")

    selected = await dataset_from_insight(
        "selected-person-profile",
        [],
        "person_profile",
    )

    assert selected == []
    assert not storage.exists(obsolete)
    assert not storage.is_dir(
        "storage/generated/selected-person-profile/datasets/avientus"
    )


@pytest.mark.asyncio
async def test_dataset_from_insight_creates_empty_target_dataset(mock_env):
    selected = await dataset_from_insight(
        "empty-person-profile",
        [],
        "person_profile",
    )

    assert selected == []
    assert get_storage().is_dir(
        "storage/generated/empty-person-profile/datasets"
    )


@pytest.mark.asyncio
async def test_dataset_from_insight_preserves_json_run_hierarchy(
    mock_env,
    monkeypatch,
):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("avientus", "startups")
    source_relative = (
        "insights/submission-ready/20260730T221500Z/"
        "checklist-gpt-5-4-mini.json"
    )
    storage.write_text(
        f"storage/startups/avientus/{source_relative}",
        '{"status":"Pass"}',
    )

    selected = await dataset_from_insight(
        "avientus-submission-ready",
        ["avientus"],
        "submission_ready",
    )

    assert len(selected) == 1
    assert storage.read_text(
        "storage/generated/avientus-submission-ready/datasets/"
        f"avientus/{source_relative}"
    ) == '{"status":"Pass"}'


@pytest.mark.asyncio
async def test_sync_datasets_always_reconciles_current_state(mocker):
    import lib.datasets.ingestion as ingestion

    ingestion._sync_locks.clear()

    calls = []

    async def fake_sync(dataset_name):
        calls.append(dataset_name)
        return ingestion.IngestionResult(dataset=dataset_name)

    mocker.patch.object(ingestion, "_sync_single_dataset", side_effect=fake_sync)

    await ingestion.sync_datasets(["person_profile"], raise_on_error=True)
    await ingestion.sync_datasets(["person_profile"], raise_on_error=True)
    await ingestion.sync_datasets(["person_profile"], raise_on_error=True, force=True)

    assert calls == [
        "person-profile",
        "person-profile",
        "person-profile",
    ]


def test_find_all_returns_selected_insight_files(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("sictic-members", "community")
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/"
        "urs-gubser-gpt-5-4-mini.md",
        "profile",
    )

    insights = InsightFile.find_all(
        skill="person_profile",
        datasets=["sictic-members"],
        selection="any",
    )

    assert len(insights) == 1
    assert insights[0].dataset == "sictic-members"
    assert insights[0].skill == "person-profile"
    assert insights[0].identifier == "urs-gubser"
    assert insights[0].subdir is True


def test_dataset_from_insight_cli_uses_explicit_contract(mocker):
    from skills.dataset_maintenance import __main__ as module

    calls = []
    expected = [
        InsightFile(
            "sictic-members",
            "person_profile",
            "manual",
            identifier="urs-gubser",
            subdir=True,
        )
    ]

    async def fake_dataset_from_insight(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    mocker.patch.object(
        module,
        "dataset_from_insight",
        side_effect=fake_dataset_from_insight,
    )

    result = CliRunner().invoke(
        module.app,
        [
            "dataset-from-insight",
            "--target-dataset",
            "sictic-members-person-profile",
            "--source-datasets",
            "sictic-members",
            "--skill",
            "person_profile",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            (
                "sictic-members-person-profile",
                ["sictic-members"],
                "person_profile",
            ),
            {"dry_run": True},
        )
    ]
    assert "Selected insights: 1" in result.output
    assert "urs-gubser-manual.md" in result.output


def test_dataset_maintenance_lifecycle_cli_uses_dataset_option(mocker):
    from skills.dataset_maintenance import __main__ as module

    calls = []

    mocker.patch.object(
        module,
        "activate_dataset_marker",
        side_effect=lambda dataset: calls.append(("activate", dataset)) or dataset,
    )
    mocker.patch.object(
        module,
        "archive_dataset_marker",
        side_effect=lambda dataset: calls.append(("archive", dataset)) or dataset,
    )

    activate_result = CliRunner().invoke(
        module.app,
        ["activate", "--dataset", "Avientus, Scanvio"],
    )
    archive_result = CliRunner().invoke(
        module.app,
        ["archive", "-d", "Avientus, Scanvio"],
    )

    assert activate_result.exit_code == 0
    assert archive_result.exit_code == 0
    assert calls == [
        ("activate", "Avientus"),
        ("activate", "Scanvio"),
        ("archive", "Avientus"),
        ("archive", "Scanvio"),
    ]
    assert "Activated: Avientus" in activate_result.output
    assert "Activated: Scanvio" in activate_result.output
    assert "Archived: Avientus" in archive_result.output
    assert "Archived: Scanvio" in archive_result.output


def test_dataset_maintenance_create_cli_initializes_startup_dossier(mock_env):
    from skills.dataset_maintenance import __main__ as module
    from lib.datasets.paths import dataset_parsed_path, dataset_raw_path
    from lib.startups.dossier import STARTUP_DATASET_SUBDIRS

    result = CliRunner().invoke(
        module.app,
        ["create", "Example Startup"],
    )

    assert result.exit_code == 0
    assert "Created startup dossier: example-startup" in result.output
    storage = get_storage()
    for root in (
        dataset_raw_path("example-startup"),
        dataset_parsed_path("example-startup"),
    ):
        for subdir in STARTUP_DATASET_SUBDIRS:
            assert storage.is_dir(f"{root}/{subdir}")
    assert storage.exists(
        f"{dataset_raw_path('example-startup')}/__active_dataset__.md"
    )


@pytest.mark.asyncio
async def test_generate_member_profiles_can_skip_index_and_source_sync(mocker):
    from lib.people.model import Person
    script = _load_script("generate_member_profiles")

    mocker.patch(
        "lib.people.discovery.persons_in_dataset",
        return_value=[Person(full_name="Urs Gubser", linkedin_id="urs-gubser")],
    )
    mock_profile = mocker.patch(
        "skills.person_profile.person_profile.person_profile",
        return_value=[Person(full_name="Urs Gubser")],
    )
    mock_dataset_from_insight = mocker.patch.object(
        script,
        "dataset_from_insight",
    )

    result = await script.generate_member_profiles(
        dataset="sictic-members",
        limit=1,
        skip_index=True,
        sync_source=False,
    )

    assert result.requested == 1
    assert result.generated == 1
    assert result.indexed is False
    mock_profile.assert_called_once_with(
        dataset_name="sictic-members",
        names=["Urs Gubser"],
        include_dataset_context=False,
    )
    mock_dataset_from_insight.assert_not_called()

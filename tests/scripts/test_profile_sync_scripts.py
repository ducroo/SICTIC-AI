import pytest
import importlib.util
import sys
from pathlib import Path

from typer.testing import CliRunner

from lib.datasets.state import activate_dataset
from lib.insights import (
    InsightHydrationResult,
    discover_insights,
    hydrate_dataset_from_insights,
)
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain


REPO_ROOT = Path(__file__).resolve().parents[2]


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
        "storage/generated/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    result = await hydrate_dataset_from_insights(
        insight_name="person_profile",
        source_dataset="sictic-members",
    )

    assert result.selected == 1
    assert result.synced == 1
    assert result.removed == 1
    assert storage.exists("storage/generated/sictic-members-person-profile/datasets/urs-gubser-gpt-5-4-mini.md")
    assert not storage.exists("storage/generated/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md")
    assert storage.read_text("storage/generated/sictic-members-person-profile/datasets/urs-gubser-gpt-5-4-mini.md") == "preferred gpt profile"


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

    result = await hydrate_dataset_from_insights(
        insight_name="person_profile",
        source_dataset="sictic-members",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.synced == 1
    assert result.removed == 1
    assert not storage.exists("storage/generated/sictic-members-person-profile/datasets/urs-gubser-gpt-5-4-mini.md")
    assert storage.exists("storage/generated/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md")


@pytest.mark.asyncio
async def test_dataset_from_insight_without_source_scans_active_datasets(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("avientus", "startups")
    _create_dataset("archived", "startups")
    activate_dataset("avientus")

    storage.write_text(
        "storage/startups/avientus/insights/person-profile/jane-doe-gpt-5-4-mini.md",
        "active profile",
    )
    storage.write_text(
        "storage/startups/archived/insights/person-profile/john-doe-gpt-5-4-mini.md",
        "archived profile",
    )

    result = await hydrate_dataset_from_insights("person_profile")

    assert result.target_dataset == "active-person-profile"
    assert result.target_path == "storage/generated/active-person-profile/datasets"
    assert result.selected == 1
    assert storage.exists("storage/generated/active-person-profile/datasets/jane-doe-gpt-5-4-mini.md")
    assert not storage.exists("storage/generated/active-person-profile/datasets/john-doe-gpt-5-4-mini.md")


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


def test_insight_discovery_returns_structured_records(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_dataset("sictic-members", "community")
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/"
        "urs-gubser-gpt-5-4-mini.md",
        "profile",
    )

    records = discover_insights(
        "person_profile",
        source_dataset="sictic-members",
    )

    assert len(records) == 1
    assert records[0].dataset == "sictic-members"
    assert records[0].skill == "person-profile"
    assert records[0].identifier == "urs-gubser"
    assert records[0].subdir is True


def test_dataset_from_insight_cli_invokes_generic_hydration(mocker):
    from skills.dataset_maintenance import __main__ as module

    expected = InsightHydrationResult(
        target_dataset="sictic-members-person-profile",
        target_path="storage/generated/sictic-members-person-profile/datasets",
        insight="person-profile",
        source_dataset="sictic-members",
        selected=2,
        dry_run=True,
    )

    calls = []

    async def fake_hydration(**kwargs):
        calls.append(kwargs)
        return expected

    mocker.patch.object(
        module,
        "hydrate_dataset_from_insights",
        side_effect=fake_hydration,
    )

    result = CliRunner().invoke(
        module.app,
        [
            "from-insight",
            "--insight-name",
            "person_profile",
            "--source-dataset",
            "sictic-members",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "insight_name": "person_profile",
            "source_dataset": "sictic-members",
            "dry_run": True,
        }
    ]
    assert "Target path: storage/generated/sictic-members-person-profile/datasets" in result.output


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
    mock_hydrate = mocker.patch.object(
        script,
        "hydrate_dataset_from_insights",
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
    mock_hydrate.assert_not_called()

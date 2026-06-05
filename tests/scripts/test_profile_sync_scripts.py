import pytest
import importlib.util
import sys
from pathlib import Path

from typer.testing import CliRunner

from lib.active_dataset import activate_dataset
from lib.dataset_from_insight import DatasetFromInsightResult, dataset_from_insight
from lib.storage import get_storage


REPO_ROOT = Path(__file__).resolve().parents[2]


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

    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/urs-gubser-qwen3-8b.md",
        "old qwen profile",
    )
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/urs-gubser-gpt-5-4-mini.md",
        "preferred gpt profile",
    )
    storage.write_text(
        "storage/community/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    result = await dataset_from_insight(
        insight_name="person_profile",
        source_dataset="sictic-members",
    )

    assert result.selected == 1
    assert result.synced == 1
    assert result.removed == 1
    assert storage.exists("storage/community/sictic-members-person-profile/datasets/urs-gubser-gpt-5-4-mini.md")
    assert not storage.exists("storage/community/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md")
    assert storage.read_text("storage/community/sictic-members-person-profile/datasets/urs-gubser-gpt-5-4-mini.md") == "preferred gpt profile"


@pytest.mark.asyncio
async def test_dataset_from_insight_dry_run_does_not_write_or_remove(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()

    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/urs-gubser-gpt-5-4-mini.md",
        "preferred gpt profile",
    )
    storage.write_text(
        "storage/community/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    result = await dataset_from_insight(
        insight_name="person_profile",
        source_dataset="sictic-members",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.synced == 1
    assert result.removed == 1
    assert not storage.exists("storage/community/sictic-members-person-profile/datasets/urs-gubser-gpt-5-4-mini.md")
    assert storage.exists("storage/community/sictic-members-person-profile/datasets/urs-gubser-qwen3-8b.md")


@pytest.mark.asyncio
async def test_dataset_from_insight_without_source_scans_active_datasets(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    activate_dataset("avientus")

    storage.write_text(
        "storage/startups/avientus/insights/person-profile/jane-doe-gpt-5-4-mini.md",
        "active profile",
    )
    storage.write_text(
        "storage/startups/archived/insights/person-profile/john-doe-gpt-5-4-mini.md",
        "archived profile",
    )

    result = await dataset_from_insight("person_profile")

    assert result.target_dataset == "active-person-profile"
    assert result.target_path == "storage/community/active-person-profile/datasets"
    assert result.selected == 1
    assert storage.exists("storage/community/active-person-profile/datasets/jane-doe-gpt-5-4-mini.md")
    assert not storage.exists("storage/community/active-person-profile/datasets/john-doe-gpt-5-4-mini.md")


@pytest.mark.asyncio
async def test_sync_datasets_force_bypasses_recent_sync_cache(mocker):
    import skills.dataset_chat.core.ingestion as ingestion

    ingestion._last_sync_times.clear()
    ingestion._sync_locks.clear()

    calls = []

    async def fake_sync(dataset_name, *, domain=None):
        calls.append((dataset_name, domain))

    mocker.patch.object(ingestion, "_sync_single_dataset", side_effect=fake_sync)

    await ingestion.sync_datasets(["person_profile"], raise_on_error=True)
    await ingestion.sync_datasets(["person_profile"], raise_on_error=True)
    await ingestion.sync_datasets(["person_profile"], raise_on_error=True, force=True)

    assert calls == [
        ("person-profile", None),
        ("person-profile", None),
    ]


def test_dataset_from_insight_cli_invokes_generic_hydration(mocker):
    import lib.dataset_from_insight as module

    expected = DatasetFromInsightResult(
        target_dataset="sictic-members-person-profile",
        target_path="storage/community/sictic-members-person-profile/datasets",
        insight="person-profile",
        source_dataset="sictic-members",
        selected=2,
        dry_run=True,
    )

    calls = []

    async def fake_dataset_from_insight(**kwargs):
        calls.append(kwargs)
        return expected

    mocker.patch.object(module, "dataset_from_insight", side_effect=fake_dataset_from_insight)

    result = CliRunner().invoke(
        module.app,
        [
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
    assert "Target path: storage/community/sictic-members-person-profile/datasets" in result.output


@pytest.mark.asyncio
async def test_generate_member_profiles_can_skip_index_and_source_sync(mocker):
    from lib.models.person import Person
    script = _load_script("generate_member_profiles")

    mocker.patch(
        "skills.person_profile.persons_in_dataset.persons_in_dataset",
        return_value=[Person(full_name="Urs Gubser", linkedin_id="urs-gubser")],
    )
    mock_profile = mocker.patch(
        "skills.person_profile.person_profile.person_profile",
        return_value=[Person(full_name="Urs Gubser")],
    )
    mock_hydrate = mocker.patch.object(script, "dataset_from_insight")

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

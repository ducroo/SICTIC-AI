import pytest
import importlib.util
import sys
from pathlib import Path

from lib.dataset_from_insight import dataset_from_insight
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
        "insights/community/sictic-members/person-profile/urs-gubser-qwen3-8b.md",
        "old qwen profile",
    )
    storage.write_text(
        "insights/community/sictic-members/person-profile/urs-gubser-gpt-5-4-mini.md",
        "preferred gpt profile",
    )
    storage.write_text(
        "derived/person-profile/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    result = await dataset_from_insight(
        target_dataset="person_profile",
        insight="person_profile",
        source_dataset="sictic-members",
    )

    assert result.selected == 1
    assert result.synced == 1
    assert result.removed == 1
    assert storage.exists("derived/person-profile/urs-gubser-gpt-5-4-mini.md")
    assert not storage.exists("derived/person-profile/urs-gubser-qwen3-8b.md")
    assert storage.read_text("derived/person-profile/urs-gubser-gpt-5-4-mini.md") == "preferred gpt profile"


@pytest.mark.asyncio
async def test_dataset_from_insight_dry_run_does_not_write_or_remove(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()

    storage.write_text(
        "insights/community/sictic-members/person-profile/urs-gubser-gpt-5-4-mini.md",
        "preferred gpt profile",
    )
    storage.write_text(
        "derived/person-profile/urs-gubser-qwen3-8b.md",
        "stale derived profile",
    )

    result = await dataset_from_insight(
        target_dataset="person_profile",
        insight="person_profile",
        source_dataset="sictic-members",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.synced == 1
    assert result.removed == 1
    assert not storage.exists("derived/person-profile/urs-gubser-gpt-5-4-mini.md")
    assert storage.exists("derived/person-profile/urs-gubser-qwen3-8b.md")


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


@pytest.mark.asyncio
async def test_sync_person_profiles_from_insights_uses_forced_index_sync(mocker):
    from lib.dataset_from_insight import DatasetFromInsightResult
    script = _load_script("sync_person_profiles_from_insights")

    expected = DatasetFromInsightResult(
        target_dataset="person-profile",
        target_path="derived/person-profile",
        insight="person-profile",
        source_dataset="sictic-members",
        selected=2,
    )
    mock_hydrate = mocker.patch.object(script, "dataset_from_insight", return_value=expected)
    mock_sync = mocker.patch("skills.dataset_chat.core.ingestion.sync_datasets")

    result = await script.sync_person_profiles_from_insights(source_dataset="sictic-members")

    assert result is expected
    mock_hydrate.assert_called_once_with(
        target_dataset="person_profile",
        insight="person_profile",
        source_dataset="sictic-members",
        dry_run=False,
    )
    mock_sync.assert_called_once_with(["person_profile"], raise_on_error=True, force=True)


@pytest.mark.asyncio
async def test_generate_member_profiles_can_skip_index_and_source_sync(mocker):
    from lib.models.person import Person
    script = _load_script("generate_member_profiles")

    mocker.patch(
        "skills.person_profile.persons_in_dataset.persons_in_dataset",
        return_value=[Person(full_name="Urs Gubser", linkedinID="urs-gubser")],
    )
    mock_profile = mocker.patch(
        "skills.person_profile.person_profile.person_profile",
        return_value=[Person(full_name="Urs Gubser")],
    )
    mock_index = mocker.patch.object(script, "sync_person_profiles_from_insights")

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
    mock_index.assert_not_called()

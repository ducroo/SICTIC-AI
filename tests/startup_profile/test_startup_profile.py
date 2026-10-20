import pytest

from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain
from skills.startup_profile.startup_profile import startup_profile
from lib.insights import InsightFile
from typer.testing import CliRunner
from skills.startup_profile.__main__ import app


@pytest.fixture(autouse=True)
def classification_skill(mocker):
    classification = {
        "sector": "EnergyTech",
        "sector_confidence": "H",
        "rationale": "Energy equipment.", "evidence": ["Deck, page 1"],
    }
    return mocker.patch(
        "skills.startup_profile.startup_profile.startup_sector_as_dict", return_value=classification,
    )


@pytest.mark.asyncio
async def test_startup_profile_saves_empty_context_response(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    save = mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.save"
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.load_repository_config",
        return_value={
            "query": "Profile this startup.",
            "llm_instructions": "Use only context.",
        },
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value="INSUFFICIENT_CONTEXT",
    )
    result = await startup_profile("Avientus")

    save.assert_called_once_with("INSUFFICIENT_CONTEXT")
    assert len(result) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_output", ["", "   "])
async def test_startup_profile_rejects_empty_llm_output(mock_env, mocker, empty_output):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    save = mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.save"
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.load_repository_config",
        return_value={
            "query": "Profile this startup.",
            "llm_instructions": "Use only context.",
        },
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value=empty_output,
    )

    with pytest.raises(ValueError, match="empty response"):
        await startup_profile("Avientus")

    save.assert_not_called()


@pytest.mark.asyncio
async def test_startup_profile_splits_query_lines_for_retrieval(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    mocker.patch("skills.startup_profile.startup_profile.InsightFile.save")
    mocker.patch(
        "skills.startup_profile.startup_profile.load_repository_config",
        return_value={
            "query": "1. Oneliner\n\n2. Industry\n3. Technology",
            "llm_instructions": "Use only context.",
        },
    )
    chat = mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value="Profile output",
    )

    await startup_profile("Avientus")

    chat.assert_awaited_once_with(
        dataset_name="avientus",
        queries=["1. Oneliner", "2. Industry", "3. Technology"],
        prompt=(
            "Query: 1. Oneliner\n\n2. Industry\n\n3. Technology\n\n"
            "Instructions: Use only context."
        ),
    )


@pytest.mark.asyncio
async def test_temporary_dossier_keeps_sources_and_manual_profile(mock_env, mocker, classification_skill):
    location = dataset_location_for_domain("temp-profile", "generated")
    storage = get_storage()
    source = f"{location.raw_rel}/supplied.md"
    storage.write_text(source, "User-provided business description.")
    manual = InsightFile("temp-profile", "startup_profile", "manual")
    manual.save("Manually reviewed profile")
    prepare = mocker.patch("lib.startups.sources.ensure_startup_dataset")
    sync = mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    chat = mocker.patch("skills.startup_profile.startup_profile.dataset_chat")

    [result] = await startup_profile("temp-profile")

    assert result.content() == "Manually reviewed profile"
    classification_skill.assert_not_awaited()
    assert storage.read_text(source) == "User-provided business description."
    prepare.assert_not_called()
    chat.assert_not_called()
    sync.assert_awaited_once_with(["temp-profile"], raise_on_error=True)


@pytest.mark.asyncio
async def test_temporary_profile_is_saved_in_its_own_dossier(mock_env, mocker, monkeypatch):
    from lib.datasets.manifest import IngestionManifest

    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    location = dataset_location_for_domain("temp-profile", "generated")
    get_storage().mkdir(location.raw_rel)
    manifest = IngestionManifest.load(get_storage(), location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()
    prepare = mocker.patch("lib.startups.sources.ensure_startup_dataset")
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    chat = mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat", return_value="Temporary profile",
    )

    [result] = await startup_profile("temp-profile")

    assert result.directory == location.insights_rel
    assert result.content().startswith("Temporary profile\n\n- **Classification:**\n")
    assert "  - **SICTIC sector:** EnergyTech" in result.content()
    assert chat.await_args.kwargs["dataset_name"] == "temp-profile"
    prepare.assert_not_called()
    [reused] = await startup_profile("temp-profile")
    assert reused.path == result.path
    chat.assert_awaited_once()


@pytest.mark.parametrize("option", ["--files", "-f"])
def test_cli_rejects_removed_file_input(option, mocker):
    workflow = mocker.patch("skills.startup_profile.__main__.startup_profile")
    result = CliRunner().invoke(app, ["--startup", "example", option, "deck.pdf"])
    assert result.exit_code == 2
    workflow.assert_not_called()


def test_python_api_rejects_removed_file_input():
    with pytest.raises(TypeError, match="files"):
        startup_profile("example", files=["deck.pdf"])


@pytest.mark.asyncio
async def test_classification_changes_invalidate_profile_and_failure_preserves_it(
    mock_env, mocker, monkeypatch, classification_skill,
):
    from lib.datasets.manifest import IngestionManifest

    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    location = dataset_location_for_domain("temp-profile", "generated")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest.load(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "unchanged-revision"
    manifest.save()
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    chat = mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat", return_value="Profile body",
    )

    [first] = await startup_profile("temp-profile")
    original = first.content()
    await startup_profile("temp-profile")
    assert chat.await_count == 1
    assert classification_skill.await_count == 2

    revised = dict(classification_skill.return_value)
    revised.update(sector="insufficient evidence", sector_confidence="L")
    classification_skill.return_value = revised
    [changed] = await startup_profile("temp-profile")
    assert chat.await_count == 2
    assert changed.path == first.path
    assert changed.content() != original
    assert "**SICTIC sector:** insufficient evidence" in changed.content()
    assert "**Product type:**" not in changed.content()
    assert "Core industry" not in chat.await_args.kwargs["prompt"]

    saved = changed.content()
    classification_skill.side_effect = RuntimeError("Classification unavailable")
    with pytest.raises(RuntimeError, match="Classification unavailable"):
        await startup_profile("temp-profile")
    assert changed.content() == saved
    assert chat.await_count == 2


def test_profile_registry_requires_sector():
    from skills.skill_registry import SKILL_REGISTRY

    assert SKILL_REGISTRY["startup-profile"].depends_on == ("startup-sector",)
    assert "startup-profile" not in SKILL_REGISTRY["startup-sector"].depends_on


@pytest.mark.asyncio
async def test_dealum_is_displayed_and_other_provider_changes_do_not_invalidate(
    mock_env, mocker, monkeypatch, classification_skill,
):
    from lib.datasets.manifest import IngestionManifest
    from lib.infrastructure.configuration import load_repository_config
    from skills.startup_sector.taxonomy import provider_record

    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    location = dataset_location_for_domain("temp-profile", "generated")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest.load(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "unchanged-revision"
    manifest.save()
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    chat = mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat", return_value="Profile body",
    )
    reference = load_repository_config("startup_sector")["taxonomies"]["dealum"]
    result = {
        "classifications": {
            "industries": {"primary": "energy", "secondary": ["defence"]},
            "technologies": {"primary": "drones", "secondary": ["autonomous-systems"]},
        },
        "confidence": "H", "rationale": "Energy offering.",
        "evidence": ["Deck, page 1: energy."],
    }
    classification = {"providers": {"dealum": provider_record(result, reference)}}
    classification_skill.return_value = classification
    [first] = await startup_profile("temp-profile")
    assert first.content().startswith("Profile body\n\n- **Classification:**\n")
    assert first.content().endswith(
        "- **Classification:**\n"
        "  - **Primary-industry:** Energy.\n"
        "  - **Secondary-industries:** Defence.\n"
        "  - **Primary-technology:** Drones.\n"
        "  - **Secondary-technologies:** Autonomous systems.\n"
    )
    assert "**Dealum industry:**" not in first.content()
    classification["providers"]["pitchbook"] = {"updated": "irrelevant to profile"}
    classification_skill.return_value = classification
    await startup_profile("temp-profile")
    assert chat.await_count == 1

    result["classifications"]["industries"]["primary"] = "defence"
    result["classifications"]["industries"]["secondary"] = []
    classification["providers"]["dealum"] = provider_record(result, reference)
    classification_skill.return_value = classification
    [changed] = await startup_profile("temp-profile")
    assert changed.path == first.path
    assert "**Primary-industry:** Defence" in changed.content()
    assert "**Secondary-industries:** None selected." in changed.content()
    assert chat.await_count == 2

    result["classifications"]["industries"]["primary"] = None
    result["classifications"]["technologies"] = {"primary": None, "secondary": []}
    result["confidence"] = "L"
    classification["providers"]["dealum"] = provider_record(result, reference)
    classification_skill.return_value = classification
    [unknown] = await startup_profile("temp-profile")
    assert "**Primary-industry:** Insufficient evidence" in unknown.content()
    assert "**Primary-technology:** Insufficient evidence" in unknown.content()
    assert "**Secondary-technologies:** None selected." in unknown.content()

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.models import Chunk
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.people.model import Person
from lib.storage import get_storage


@pytest.fixture
def local_profiles(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    module = importlib.import_module("skills.person_profile.person_profile")
    location = dataset_location_for_domain("acme", "startups")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()
    monkeypatch.setattr(module, "sync_datasets", AsyncMock())
    discovery_module = importlib.import_module("skills.persons_in_dataset.persons_in_dataset")
    monkeypatch.setattr(discovery_module, "sync_datasets", AsyncMock())
    monkeypatch.setattr(module, "LinkedInResolver", Mock())
    module.LinkedInResolver.return_value.get_profiles.side_effect = lambda people: people
    discovery = AsyncMock(return_value={"names": ["Jane Doe", "Jane Doe", "Ann Advisor"]})
    monkeypatch.setattr(discovery_module, "dataset_chat_json", discovery)
    module.discovery_test_module = discovery_module
    chunk = Chunk(chunk_id="cv-1", document_name="cv.pdf", page_number=1, last_modified=0.0, text="Jane Doe founded Acme. Ann Advisor advises Acme.", score=1.0)
    monkeypatch.setattr(module, "build_person_dossier", AsyncMock(return_value=([chunk], [])))
    monkeypatch.setattr(module, "generate_markdown", AsyncMock(return_value="Documented founder evidence: cv.pdf — page 1."))
    InsightFile("acme", "persons_in_dataset", "manual").save(
        "| full-name | linkedin-id |\n|---|---|\n| Jane Doe | |\n| Ann Advisor | |\n"
    )
    return module


@pytest.mark.asyncio
async def test_standard_profile_reads_roster_and_enriches_without_discovery(local_profiles):
    module = local_profiles
    people = await module.person_profile_as_person_objects(
        "acme",
    )
    assert [person.full_name for person in people] == ["Jane Doe", "Ann Advisor"]
    assert all(person.person_profile_markdown.startswith("Full-name:") for person in people)
    assert module.LinkedInResolver.return_value.get_profiles.call_count == 1
    assert module.generate_markdown.await_count == 2
    assert all("cv.pdf" in call.args[0] for call in module.generate_markdown.await_args_list)

    # The editable roster is reused; derived profiles use the revision cache.
    await module.person_profile_as_person_objects(
        "acme",
    )
    module.discovery_test_module.dataset_chat_json.assert_not_awaited()
    assert module.generate_markdown.await_count == 2


@pytest.mark.asyncio
async def test_standard_profile_includes_linkedin_and_founder_traits_and_reuses_cache(local_profiles):
    module = local_profiles
    person = Person(full_name="Jane Doe", linkedin_id="jane-doe-123", linkedin_profile={"headline": "LinkedIn biography"})
    original = await module._generate_single_profile("acme", person)
    result = await module._generate_single_profile("acme", person)
    assert result.path == original.path
    assert result.filename == "jane-doe-123-test-model-1b.md"
    module.generate_markdown.assert_awaited_once()
    prompt = module.generate_markdown.await_args.args[0]
    assert "LinkedIn biography" in prompt
    assert "cv.pdf" in prompt
    assert "Founder traits — N001" in prompt
    assert "Insufficient information" in prompt


@pytest.mark.asyncio
async def test_explicit_person_does_not_expand_target_set(local_profiles):
    people = await local_profiles.person_profile_as_person_objects(
        "acme", names="Jane Doe",
    )
    assert [person.full_name for person in people] == ["Jane Doe"]
    assert local_profiles.generate_markdown.await_count == 1


@pytest.mark.asyncio
async def test_empty_roster_returns_no_people(local_profiles):
    InsightFile("acme", "persons_in_dataset", "manual").save("| full-name | linkedin-id |\n|---|---|\n")
    assert await local_profiles.person_profile_as_person_objects(
        "acme",
    ) == []
    local_profiles.generate_markdown.assert_not_awaited()
    local_profiles.LinkedInResolver.assert_not_called()


@pytest.mark.parametrize("result", [{"names": [""]}, {"names": [None]}, [], {}])
def test_discovery_reviewer_rejects_invalid_names(result):
    module = importlib.import_module("skills.persons_in_dataset.persons_in_dataset")
    assert module._review_person_names(result).problems


@pytest.mark.asyncio
async def test_manual_roster_overrides_existing_json_discovery(local_profiles):
    InsightFile("acme", "persons_in_dataset", "test-model", identifier="data-room", subdir=True, extension="json").save(
        '{"names": ["Obsolete Discovery"]}'
    )
    roster = InsightFile("acme", "persons_in_dataset", "manual")
    roster.save(
        "| full-name | linkedin-id | email-addresses |\n"
        "|---|---|---|\n"
        "| Takuya Takahashi | takuya | takuya@example.com |\n"
    )
    people = local_profiles.persons_in_dataset("acme")
    assert [person.full_name for person in people] == ["Takuya Takahashi"]
    assert people[0].linkedin_id == "takuya"
    local_profiles.discovery_test_module.dataset_chat_json.assert_not_awaited()
    local_profiles.LinkedInResolver.assert_not_called()


@pytest.mark.asyncio
async def test_empty_manual_roster_does_not_trigger_discovery(local_profiles):
    InsightFile("acme", "persons_in_dataset", "manual").save(
        "| full-name | linkedin-id |\n|---|---|\n"
    )
    assert local_profiles.persons_in_dataset("acme") == []
    local_profiles.discovery_test_module.dataset_chat_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_roster_never_triggers_discovery(local_profiles):
    location = dataset_location_for_domain("missing-roster", "startups")
    get_storage().mkdir(location.raw_rel)
    with pytest.raises(FileNotFoundError, match="run the persons_in_dataset skill first"):
        await local_profiles.person_profile_as_person_objects(
            "missing-roster",
        )
    local_profiles.discovery_test_module.dataset_chat_json.assert_not_awaited()
    local_profiles.sync_datasets.assert_not_awaited()
    local_profiles.generate_markdown.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("linkedin_id,emails,expected", [
    ("jane-123", ["unrelated@example.com"], "jane-123"),
    ("", ["unrelated@example.com"], "unrelated-example-com"),
    ("", [], "jane-doe"),
])
async def test_profile_filename_uses_standard_identifier_order(local_profiles, linkedin_id, emails, expected):
    person = Person(full_name="Jane Doe", linkedin_id=linkedin_id, email_addresses=emails)
    result = await local_profiles._generate_single_profile(
        "acme", person,
    )
    assert result.filename == f"{expected}-test-model-1b.md"


@pytest.mark.asyncio
async def test_manual_profile_remains_authoritative(local_profiles):
    manual = InsightFile("acme", "person_profile", "manual", identifier="jane-123", subdir=True)
    manual.save("Human reviewed profile")
    result = await local_profiles._generate_single_profile(
        "acme", Person(full_name="Jane Doe", linkedin_id="jane-123"),
    )
    assert result.path == manual.path
    assert result.content() == "Human reviewed profile"
    local_profiles.generate_markdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_only_person_uses_email_identifier(local_profiles):
    result = await local_profiles._generate_single_profile(
        "acme", Person(email_addresses=["person@example.com"]),
    )
    assert result.filename == "person-example-com-test-model-1b.md"


@pytest.mark.asyncio
async def test_registry_profiles_are_reused_by_team_workflow(local_profiles, monkeypatch):
    from skills.skill_registry import SKILL_REGISTRY

    profiles = local_profiles
    team = importlib.import_module("skills.team_profile_revised.team_profile_revised")
    startup = InsightFile("acme", "startup_profile", "manual")
    startup.save("Acme startup evidence")
    monkeypatch.setattr(team, "ensure_startup_dataset", AsyncMock(return_value=SimpleNamespace(dataset_slug="acme")))
    monkeypatch.setattr(team, "sync_datasets", AsyncMock())
    monkeypatch.setattr(team, "startup_profile", AsyncMock(return_value=[startup]))
    monkeypatch.setattr(team, "_run_audits", AsyncMock(return_value=[]))
    monkeypatch.setattr(team, "generate_markdown", AsyncMock(return_value="Team synthesis"))

    original = await SKILL_REGISTRY["person-profile"].func("acme")
    contents = {insight.path: insight.content() for insight in original}
    assert profiles.generate_markdown.await_count == 2
    await team.team_profile_revised("acme")
    await SKILL_REGISTRY["person-profile"].func("acme")
    await team.team_profile_revised("acme")

    assert profiles.generate_markdown.await_count == 2
    assert {insight.path: insight.content() for insight in original} == contents
    team._run_audits.assert_awaited_once()
    team.generate_markdown.assert_awaited_once()

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
    discovery = AsyncMock()
    monkeypatch.setattr(discovery_module, "reconcile_people", discovery)
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
    module.discovery_test_module.reconcile_people.assert_not_awaited()
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


@pytest.mark.parametrize("result", [{"names": [""]}, {"names": ["  "]}, {"names": [None]}, [], {}])
def test_discovery_schema_rejects_invalid_names(result):
    module = importlib.import_module("skills.persons_in_dataset.persons_in_dataset")
    from lib.infrastructure.ai_text_generation.json import validate_json_schema

    schema = module.load_repository_config("persons_in_dataset", "discovery")["response_schema"]
    with pytest.raises(ValueError):
        validate_json_schema(result, schema)


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
    local_profiles.discovery_test_module.reconcile_people.assert_not_awaited()
    local_profiles.LinkedInResolver.assert_not_called()


@pytest.mark.asyncio
async def test_empty_manual_roster_does_not_trigger_discovery(local_profiles):
    InsightFile("acme", "persons_in_dataset", "manual").save(
        "| full-name | linkedin-id |\n|---|---|\n"
    )
    assert local_profiles.persons_in_dataset("acme") == []
    local_profiles.discovery_test_module.reconcile_people.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_roster_never_triggers_discovery(local_profiles):
    location = dataset_location_for_domain("missing-roster", "startups")
    get_storage().mkdir(location.raw_rel)
    with pytest.raises(FileNotFoundError, match="run the persons_in_dataset skill first"):
        await local_profiles.person_profile_as_person_objects(
            "missing-roster",
        )
    local_profiles.discovery_test_module.reconcile_people.assert_not_awaited()
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


def _partial_linkedin_failure(module):
    from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind

    InsightFile("acme", "persons_in_dataset", "manual").save(
        "| full-name | linkedin-id |\n|---|---|\n| Jane Doe | jane-doe |\n| Ann Advisor | ann-advisor |\n"
    )

    def resolve(people):
        people[0].linkedin_profile = {"headline": "Retrieved founder background"}
        raise InfrastructureError("Pending profiles", provider="linkedin", operation="get_profiles",
                                  kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE)

    module.LinkedInResolver.return_value.get_profiles.side_effect = resolve


@pytest.mark.asyncio
async def test_partial_retrieval_keeps_enrichment_and_cv_evidence(local_profiles):
    module = local_profiles
    _partial_linkedin_failure(module)
    people = await module.person_profile_as_person_objects("acme")
    assert len(people) == 2
    assert "INCOMPLETE" not in people[0].person_profile_markdown
    assert "INCOMPLETE" in people[1].person_profile_markdown
    prompts = [call.args[0] for call in module.generate_markdown.await_args_list]
    assert any("Retrieved founder background" in prompt for prompt in prompts)
    assert all("cv.pdf" in prompt for prompt in prompts)
    # Acquisition failure does not force regeneration of reusable profiles.
    await module.person_profile_as_person_objects("acme")
    assert module.generate_markdown.await_count == 2


@pytest.mark.asyncio
async def test_failed_retrieval_without_evidence_saves_note_without_llm(local_profiles):
    module = local_profiles
    _partial_linkedin_failure(module)
    module.build_person_dossier.return_value = ([], [])
    people = await module.person_profile_as_person_objects("acme")
    assert "No relevant information found." in people[1].person_profile_markdown
    assert "INCOMPLETE" in people[1].person_profile_markdown
    module.generate_markdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_profile_preserved_after_retrieval_failure(local_profiles):
    module = local_profiles
    _partial_linkedin_failure(module)
    manual = InsightFile("acme", "person_profile", "manual", identifier="ann-advisor", subdir=True)
    manual.save("Human reviewed background")
    people = await module.person_profile_as_person_objects("acme")
    assert manual.content() == "Human reviewed background"
    assert "INCOMPLETE" not in people[1].person_profile_markdown
    module.generate_markdown.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("bug"), OSError("storage failure")])
async def test_unexpected_retrieval_errors_still_raise(local_profiles, error):
    local_profiles.LinkedInResolver.return_value.get_profiles.side_effect = error
    with pytest.raises(type(error), match=str(error)):
        await local_profiles.person_profile("acme")
    local_profiles.generate_markdown.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", ["team_profile", "team_profile_revised"])
async def test_team_workflows_continue_after_partial_retrieval(local_profiles, monkeypatch, skill):
    _partial_linkedin_failure(local_profiles)
    team = importlib.import_module(f"skills.{skill}.{skill}")
    preparation = AsyncMock(return_value=SimpleNamespace(dataset_slug="acme"))
    monkeypatch.setattr("lib.startups.sources.ensure_startup_dataset", preparation)
    monkeypatch.setattr(team, "sync_datasets", AsyncMock())
    monkeypatch.setattr(team, "generate_markdown", AsyncMock(return_value="Team report with evidence limitations"))
    if skill == "team_profile_revised":
        monkeypatch.setattr(team, "ensure_startup_dataset", preparation)
        monkeypatch.setattr(team, "startup_profile", AsyncMock(return_value=[]))
        monkeypatch.setattr(team, "_run_audits", AsyncMock(return_value=[]))
    else:
        monkeypatch.setattr(team, "dataset_search", AsyncMock(return_value=[]))
    result = await getattr(team, skill)("acme")
    assert len(result) == 1
    if skill == "team_profile_revised":
        context = team._run_audits.await_args.args[1]
    else:
        context = team.generate_markdown.await_args.args[0]
    assert "INCOMPLETE" in context
    assert "Jane Doe" in context and "Ann Advisor" in context


@pytest.mark.asyncio
async def test_generation_failure_still_raises_after_partial_retrieval(local_profiles):
    _partial_linkedin_failure(local_profiles)
    local_profiles.generate_markdown.side_effect = RuntimeError("generation failed")
    with pytest.raises(RuntimeError, match="Failed to generate 2 person profile"):
        await local_profiles.person_profile("acme")


@pytest.mark.asyncio
async def test_no_linkedin_id_or_evidence_is_not_a_retrieval_failure(local_profiles):
    local_profiles.build_person_dossier.return_value = ([], [])
    people = await local_profiles.person_profile_as_person_objects("acme")
    assert all("No relevant information found." in p.person_profile_markdown for p in people)
    assert all("INCOMPLETE" not in p.person_profile_markdown for p in people)
    local_profiles.generate_markdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_provider_response_still_blocks_profile(local_profiles):
    from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind

    error = InfrastructureError("invalid response", provider="apify", operation="get_profiles",
                                kind=InfrastructureErrorKind.INVALID_RESPONSE)
    local_profiles.LinkedInResolver.return_value.get_profiles.side_effect = error
    with pytest.raises(InfrastructureError, match="invalid response"):
        await local_profiles.person_profile("acme")
    local_profiles.generate_markdown.assert_not_awaited()

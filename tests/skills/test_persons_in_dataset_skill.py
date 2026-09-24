import importlib
from unittest.mock import AsyncMock, Mock

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.chunking import build_chunk
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.people.discovery import persons_in_dataset as read_roster, manual_persons_in_dataset
from lib.people.model import Person
from lib.storage import get_storage


@pytest.fixture
def discovery(mock_env, monkeypatch):
    location = dataset_location_for_domain("acme", "startups")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    module = importlib.import_module("skills.persons_in_dataset.persons_in_dataset")
    monkeypatch.setattr(module, "sync_datasets", AsyncMock())
    monkeypatch.setattr(module, "LinkedInResolver", Mock())
    resolver = module.LinkedInResolver.return_value
    resolver.get_cached_persons.return_value = []
    resolver.resolve_pending_profiles.return_value = []
    resolver.get_profiles.side_effect = lambda people: people
    monkeypatch.setattr(module, "PersonExtractor", Mock())
    module.PersonExtractor.return_value.extract.return_value = []
    monkeypatch.setattr(module, "_scan", Mock(side_effect=lambda *_: ([Person(full_name="Jane Doe"), Person(full_name="Ann Advisor")], [])))
    monkeypatch.setattr(module, "WebSearchAdapter", Mock())
    module.WebSearchAdapter.return_value.search.return_value = []
    monkeypatch.setattr(module, "search_people", Mock(return_value=[]))
    monkeypatch.setattr(module, "website_from_evidence", Mock(return_value=None))
    monkeypatch.setattr(module, "startup_website_import", Mock(return_value=Mock(failed_pages=0)))
    monkeypatch.setattr(module, "dataset_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "reconcile_people", AsyncMock(side_effect=lambda people, *_args, **_kwargs: people))

    async def profile(_dataset):
        artifact = InsightFile("acme", "startup_profile", "ollama/test_model:1b")
        artifact.save("Acme startup context")
        return [artifact]

    monkeypatch.setattr(module, "startup_profile", AsyncMock(side_effect=profile))
    return module


@pytest.mark.asyncio
async def test_names_without_linkedin_create_generated_roster_and_reuse_before_sync(discovery):
    artifacts = await discovery.persons_in_dataset("acme")
    assert len(artifacts) == 1
    assert artifacts[0].filename == "persons-in-dataset-acme-test-model-1b.md"
    assert manual_persons_in_dataset("acme") is None
    assert [p.full_name for p in read_roster("acme")] == ["Jane Doe", "Ann Advisor"]
    content = artifacts[0].content()
    assert "**INCOMPLETE:**" not in content
    assert f"`{artifacts[0].filename}`" in content
    assert "`persons-in-dataset-acme-manual.md`" in content
    assert discovery.reconcile_people.await_args.kwargs["startup_context"] == "Acme startup context"
    # dataset_search owns the later synchronization after profile acquisition.
    discovery.sync_datasets.assert_awaited_once_with(["acme"], raise_on_error=True)
    discovery.sync_datasets.reset_mock()
    discovery.startup_profile.reset_mock()
    again = await discovery.persons_in_dataset("acme")
    assert again[0].path == artifacts[0].path
    discovery.sync_datasets.assert_not_awaited()
    discovery.startup_profile.assert_not_awaited()
    assert discovery.reconcile_people.await_count == 1
    assert discovery.LinkedInResolver.return_value.resolve_pending_profiles.call_count == 2


@pytest.mark.asyncio
async def test_weighted_shortlist_precedes_search_and_preserves_independent_sources(discovery, monkeypatch):
    config = discovery.load_repository_config("persons_in_dataset", "discovery")
    config["ner_max_candidates"] = 1
    original_config = discovery.load_repository_config
    monkeypatch.setattr(discovery, "load_repository_config", lambda *sections: config if sections == ("persons_in_dataset", "discovery") else original_config(*sections))
    crowded = build_chunk("Several names", "paper.md", 1, 0)
    dedicated = build_chunk("Strong Candidate", "cv.md", 1, 0)
    strong = Person(full_name="Strong Candidate", mentions=[dedicated])
    weak = Person(full_name="Weak Candidate", mentions=[crowded])
    contact = Person(linkedin_id="explicit-id", mentions=[crowded])
    email = Person(email_addresses=["person@example.com"], mentions=[crowded])
    website = Person(full_name="Website Person", mentions=[crowded, build_chunk("Website Person", "website/team.md", 1, 0)])
    # Strong ranks first; website survives independently despite the cutoff.
    strong.mentions.append(build_chunk("Strong Candidate", "employment.md", 1, 0))
    discovery._scan.side_effect = lambda *_: ([strong, weak, contact, email, website], [])
    discovery.LinkedInResolver.return_value.get_cached_persons.return_value = [Person(full_name="Cached Person", linkedin_id="cached-id")]
    discovery.PersonExtractor.return_value.extract.return_value = [Person(full_name="Web Search Person")]
    discovery.search_people.return_value = [Person(linkedin_id="search-id")]
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    discovery.search_people.assert_called_once()
    assert discovery.search_people.call_args.args == ("acme",)
    assert "Weak Candidate" not in [p.full_name for p in people]
    assert {"Strong Candidate", "Website Person", "Web Search Person"} <= {p.full_name for p in people}
    assert {p.linkedin_id for p in people} >= {"explicit-id", "cached-id", "search-id"}
    assert any(p.email_addresses == ["person@example.com"] for p in people)


@pytest.mark.asyncio
async def test_new_raw_linkedin_profile_invalidates_before_index_revision_changes(discovery):
    await discovery.persons_in_dataset("acme")
    location = dataset_location_for_domain("acme", "startups")

    def collect():
        get_storage().write_text(f"{location.raw_rel}/linkedin/jane.json", '{"fullName":"Jane Doe"}')
        return []

    discovery.LinkedInResolver.return_value.resolve_pending_profiles.side_effect = collect
    await discovery.persons_in_dataset("acme")
    assert discovery.reconcile_people.await_count == 2


@pytest.mark.asyncio
async def test_startup_profile_edit_alone_does_not_invalidate_roster(discovery):
    await discovery.persons_in_dataset("acme")
    InsightFile("acme", "startup_profile", "manual").save("Reviewed startup context")
    await discovery.persons_in_dataset("acme")
    assert discovery.reconcile_people.await_count == 1
    discovery.startup_profile.assert_awaited_once_with("acme")


@pytest.mark.asyncio
async def test_manual_roster_stops_discovery_after_pending_collection(discovery):
    insight = InsightFile("acme", "persons_in_dataset", "manual")
    insight.save("| full-name | linkedin-id |\n|---|---|\n| Reviewed Person | reviewed-id |\n")
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert [p.linkedin_id for p in people] == ["reviewed-id"]
    discovery.LinkedInResolver.return_value.resolve_pending_profiles.assert_called_once()
    discovery.LinkedInResolver.return_value.get_profiles.assert_not_called()
    discovery.sync_datasets.assert_not_awaited()
    discovery.startup_profile.assert_not_awaited()
    discovery.PersonExtractor.assert_not_called()


@pytest.mark.asyncio
async def test_empty_manual_roster_remains_authoritative(discovery):
    InsightFile("acme", "persons_in_dataset", "manual").save("| full-name | linkedin-id |\n|---|---|\n")
    artifacts = await discovery.persons_in_dataset("acme")
    assert len(artifacts) == 1
    assert read_roster("acme") == []
    discovery.sync_datasets.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_created_during_discovery_is_not_overwritten(discovery):
    async def reconcile(people, *args, **kwargs):
        InsightFile("acme", "persons_in_dataset", "manual").save(
            "| full-name | linkedin-id |\n|---|---|\n| Reviewed Name | |\n")
        return people

    discovery.reconcile_people.side_effect = reconcile
    artifacts = await discovery.persons_in_dataset("acme")
    assert artifacts[0].model != "manual"
    assert read_roster("acme")[0].full_name == "Reviewed Name"


@pytest.mark.asyncio
async def test_no_people_does_not_freeze_empty_roster(discovery):
    discovery.reconcile_people.side_effect = None
    discovery.reconcile_people.return_value = []
    assert await discovery.persons_in_dataset("acme") == []
    with pytest.raises(FileNotFoundError):
        read_roster("acme")
    discovery.reconcile_people.return_value = [Person(full_name="Jane Doe")]
    assert len(await discovery.persons_in_dataset("acme")) == 1


@pytest.mark.asyncio
async def test_invalid_discovery_does_not_save_a_roster(discovery):
    discovery.reconcile_people.side_effect = ValueError("Invalid generated schema")
    with pytest.raises(ValueError):
        await discovery.persons_in_dataset("acme")
    with pytest.raises(FileNotFoundError):
        read_roster("acme")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["resolve_pending_profiles", "get_profiles"])
async def test_unavailable_profiles_add_markdown_notice_without_changing_reuse(discovery, operation):
    resolver = discovery.LinkedInResolver.return_value
    getattr(resolver, operation).side_effect = InfrastructureError(
        "Pending profiles", kind=InfrastructureErrorKind.RESOURCE_BUSY, provider="linkedin", operation="get_profiles")
    artifacts = await discovery.persons_in_dataset("acme")
    assert len(read_roster("acme")) == 2
    assert artifacts[0].content().startswith("> **INCOMPLETE:**")
    assert artifacts[0].is_reusable()
    assert artifacts[0].find(selection="reusable") is not None
    await discovery.persons_in_dataset("acme")
    assert discovery.reconcile_people.await_count == 1


@pytest.mark.asyncio
async def test_search_credit_failure_preserves_other_evidence(discovery, monkeypatch):
    from lib.people.linkedin.search import search_people
    monkeypatch.setattr(discovery, "search_people", search_people)
    discovery.WebSearchAdapter.return_value.search.side_effect = InfrastructureError(
        "Credit exhausted", kind=InfrastructureErrorKind.PERMISSION_DENIED, provider="apify", operation="run_actor")
    artifacts = await discovery.persons_in_dataset("acme")
    assert len(read_roster("acme")) == 2
    assert artifacts[0].content().startswith("> **INCOMPLETE:**")
    assert artifacts[0].is_reusable()


@pytest.mark.asyncio
async def test_pending_failure_does_not_bypass_existing_reusable_roster(discovery):
    original = (await discovery.persons_in_dataset("acme"))[0].content()
    discovery.LinkedInResolver.return_value.resolve_pending_profiles.side_effect = InfrastructureError(
        "Unavailable", kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE, provider="linkedin", operation="get_profiles")
    artifacts = await discovery.persons_in_dataset("acme")
    assert artifacts[0].content() == original
    assert discovery.reconcile_people.await_count == 1


@pytest.mark.asyncio
async def test_manual_roster_wins_even_if_profiles_unavailable(discovery):
    InsightFile("acme", "persons_in_dataset", "manual").save("| full-name | linkedin-id |\n|---|---|\n| Reviewed Person | reviewed-id |\n")
    discovery.LinkedInResolver.return_value.resolve_pending_profiles.side_effect = InfrastructureError(
        "Unavailable", kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE, provider="linkedin", operation="get_profiles")
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert [p.linkedin_id for p in people] == ["reviewed-id"]
    discovery.reconcile_people.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_pending_collection_error_still_propagates(discovery):
    discovery.LinkedInResolver.return_value.resolve_pending_profiles.side_effect = RuntimeError("still being processed")
    with pytest.raises(RuntimeError, match="still being processed"):
        await discovery.persons_in_dataset("acme")
    discovery.reconcile_people.assert_not_awaited()
    discovery.startup_profile.assert_not_awaited()
    with pytest.raises(FileNotFoundError):
        read_roster("acme")


@pytest.mark.asyncio
async def test_unexpected_profile_error_still_prevents_save(discovery):
    discovery.LinkedInResolver.return_value.get_profiles.side_effect = RuntimeError("still being processed")
    with pytest.raises(RuntimeError):
        await discovery.persons_in_dataset("acme")
    discovery.reconcile_people.assert_not_awaited()
    with pytest.raises(FileNotFoundError):
        read_roster("acme")


@pytest.mark.asyncio
async def test_documented_website_import_uses_existing_skill(discovery):
    discovery.website_from_evidence.return_value = "https://acme.example"
    await discovery.persons_in_dataset("acme")
    discovery.startup_website_import.assert_called_once_with("acme", "https://acme.example")
    assert discovery._scan.call_count == 2


@pytest.mark.asyncio
async def test_cached_identity_and_metadata_survive_discovery(discovery):
    cached = Person(full_name="Jane Doe", linkedin_id="jane-id", email_addresses=["jane@example.com"], linkedin_profile={"headline": "Founder"})
    discovery.LinkedInResolver.return_value.get_cached_persons.return_value = [cached]
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    jane = next(person for person in people if person.linkedin_id == "jane-id")
    assert jane.email_addresses == cached.email_addresses
    assert jane.linkedin_profile == cached.linkedin_profile


@pytest.mark.asyncio
async def test_distinct_linkedin_ids_are_not_merged(discovery):
    discovery.LinkedInResolver.return_value.get_cached_persons.return_value = [
        Person(full_name="Jane Doe", linkedin_id="jane-one"),
        Person(full_name="Jane Doe", linkedin_id="jane-two"),
    ]
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert {p.linkedin_id for p in people if p.linkedin_id} == {"jane-one", "jane-two"}


def test_generated_discovery_json_is_not_a_roster_input(mock_env):
    get_storage().mkdir(dataset_location_for_domain("acme", "startups").raw_rel)
    InsightFile("acme", "persons_in_dataset", "test", extension="json").save('{"persons":[]}')
    with pytest.raises(FileNotFoundError):
        read_roster("acme")


@pytest.mark.asyncio
async def test_nonstartup_dataset_does_not_call_startup_workflows(discovery):
    get_storage().mkdir(dataset_location_for_domain("other-community", "community").raw_rel)
    await discovery.persons_in_dataset("other-community")
    discovery.startup_profile.assert_not_awaited()
    discovery.startup_website_import.assert_not_called()
    discovery.WebSearchAdapter.assert_not_called()


@pytest.mark.asyncio
async def test_startup_context_comes_only_from_public_skill(discovery):
    InsightFile("acme", "startup_profile", "old-model", config_key="old-settings").save("Stale profile")
    # Even a separate manual artifact is selected by startup_profile, not here.
    InsightFile("acme", "startup_profile", "manual").save("Other stored profile")
    await discovery.persons_in_dataset("acme")
    discovery.startup_profile.assert_awaited_once_with("acme")
    assert discovery.reconcile_people.await_args.kwargs["startup_context"] == "Acme startup context"


@pytest.mark.asyncio
async def test_empty_website_crawl_preserves_dataset_candidates(discovery):
    discovery.website_from_evidence.return_value = "https://acme.example"
    discovery.startup_website_import.side_effect = InfrastructureError(
        "Website import saved no HTML pages", provider="website", operation="import",
        kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
    )
    [artifact] = await discovery.persons_in_dataset("acme")
    assert artifact.content().startswith("> **INCOMPLETE:**")
    assert [p.full_name for p in read_roster("acme")] == ["Jane Doe", "Ann Advisor"]
    assert discovery._scan.call_count == 1
    assert artifact.is_reusable()


@pytest.mark.asyncio
async def test_partial_website_crawl_uses_saved_pages_and_marks_incomplete(discovery):
    discovery.website_from_evidence.return_value = "https://acme.example"
    discovery.startup_website_import.return_value.failed_pages = 2
    [artifact] = await discovery.persons_in_dataset("acme")
    assert artifact.content().startswith("> **INCOMPLETE:**")
    assert discovery._scan.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("storage failure"), ValueError("invalid input")])
async def test_unexpected_website_errors_still_raise(discovery, error):
    discovery.website_from_evidence.return_value = "https://acme.example"
    discovery.startup_website_import.side_effect = error
    with pytest.raises(type(error), match=str(error)):
        await discovery.persons_in_dataset("acme")
    discovery.reconcile_people.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_company_search_regardless_of_candidate_count(discovery, monkeypatch):
    from lib.people.linkedin.search import search_people
    monkeypatch.setattr(discovery, "search_people", search_people)
    website = build_chunk("Team directory", "website/team.md", 1, 0)
    discovery._scan.side_effect = lambda *_: (
        [Person(full_name=f"Candidate {i}", mentions=[website]) for i in range(100)], []
    )
    discovery.WebSearchAdapter.return_value.search.return_value = [{
        "title": "Employee at Acme", "snippet": "Acme team member",
        "link": "https://linkedin.com/in/discovered-employee",
    }]
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    discovery.WebSearchAdapter.return_value.search.assert_called_once_with(
        'site:linkedin.com/in/ "acme" (founder OR employee OR team)', num_results=10,
    )
    assert any(p.linkedin_id == "discovered-employee" for p in people)
    assert any(p.full_name == "Candidate 99" for p in people)

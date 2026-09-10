import importlib
from unittest.mock import AsyncMock, Mock

import pytest

from lib.insights import InsightFile
from lib.people.model import Person
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from lib.people.discovery import persons_in_dataset as read_roster


@pytest.fixture
def discovery(mock_env, monkeypatch):
    get_storage().mkdir(dataset_location_for_domain("acme", "startups").raw_rel)
    module = importlib.import_module("skills.persons_in_dataset.persons_in_dataset")
    monkeypatch.setattr(module, "sync_datasets", AsyncMock())
    monkeypatch.setattr(module, "LinkedInResolver", Mock())
    module.LinkedInResolver.return_value.get_cached_persons.return_value = []
    monkeypatch.setattr(module, "dataset_chat_json", AsyncMock(return_value={"names": ["Jane Doe", "Jane Doe", "Ann Advisor"]}))
    return module


@pytest.mark.asyncio
async def test_names_without_linkedin_create_one_editable_roster(discovery):
    artifacts = await discovery.persons_in_dataset("acme")
    assert len(artifacts) == 1
    assert artifacts[0].path.endswith("persons-in-dataset-acme-manual.md")
    assert [p.full_name for p in read_roster("acme")] == ["Jane Doe", "Ann Advisor"]
    original = artifacts[0].content()
    await discovery.persons_in_dataset("acme")
    assert artifacts[0].content() == original
    assert discovery.dataset_chat_json.await_count == 1
    assert discovery.sync_datasets.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, {"names": []}])
async def test_no_evidence_does_not_freeze_empty_roster(discovery, result):
    discovery.dataset_chat_json.return_value = result
    assert await discovery.persons_in_dataset("acme") == []
    with pytest.raises(FileNotFoundError, match="run the persons_in_dataset skill"):
        read_roster("acme")
    discovery.dataset_chat_json.return_value = {"names": ["Jane Doe"]}
    assert len(await discovery.persons_in_dataset("acme")) == 1


@pytest.mark.asyncio
async def test_manual_created_during_search_wins(discovery):
    async def search(**kwargs):
        InsightFile("acme", "persons_in_dataset", "manual").save(
            "| full-name | linkedin-id |\n|---|---|\n| Reviewed Name | |\n"
        )
        return {"names": ["Unreviewed Name"]}
    discovery.dataset_chat_json.side_effect = search
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert [p.full_name for p in people] == ["Reviewed Name"]


@pytest.mark.asyncio
async def test_invalid_discovery_does_not_save_a_roster(discovery):
    discovery.dataset_chat_json.return_value = {"names": [None]}
    with pytest.raises(ValueError):
        await discovery.persons_in_dataset("acme")
    with pytest.raises(FileNotFoundError):
        read_roster("acme")


@pytest.mark.asyncio
async def test_dataset_linkedin_ids_survive_empty_name_search(discovery):
    directory = dataset_location_for_domain("acme", "startups").parsed_rel
    get_storage().write_text(
        f"{directory}/team/contacts.md",
        "https://www.linkedin.com/in/jane-doe/?trk=team\n"
        "https://ch.linkedin.com/in/jane-doe/\n"
        "linkedin.com/in/ann-advisor\n"
        "https://www.linkedin.com/company/acme/\n",
    )
    discovery.dataset_chat_json.return_value = None
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert {p.linkedin_id for p in people} == {"jane-doe", "ann-advisor"}
    assert len(people) == 2
    assert len(read_roster("acme")) == 2


@pytest.mark.asyncio
async def test_named_link_associates_name_with_linkedin_id(discovery):
    directory = dataset_location_for_domain("acme", "startups").parsed_rel
    get_storage().write_text(
        f"{directory}/team.md",
        "[Jane Doe](https://www.linkedin.com/in/jane-doe/)\n",
    )
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert len(people) == 2
    assert people[0].full_name == "Jane Doe"
    assert people[0].linkedin_id == "jane-doe"


@pytest.mark.asyncio
async def test_manual_roster_prevents_document_scan(discovery, monkeypatch):
    InsightFile("acme", "persons_in_dataset", "manual").save(
        "| full-name | linkedin-id |\n|---|---|\n"
    )
    def forbidden(*args):
        raise AssertionError("Manual roster must prevent discovery")
    monkeypatch.setattr(discovery, "_add_dataset_linkedin_ids", forbidden)
    assert await discovery.persons_in_dataset_as_person_objects("acme") == []
    discovery.sync_datasets.assert_not_awaited()
    discovery.dataset_chat_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_person_identity_and_metadata_survive_name_discovery(discovery):
    cached = Person(
        full_name="Jane Doe", linkedin_id="jane-123",
        email_addresses=["jane@example.com"],
        linkedin_profile={"headline": "Known profile"},
    )
    discovery.LinkedInResolver.return_value.get_cached_persons.return_value = [cached]
    discovery.dataset_chat_json.return_value = {"names": ["Jane Doe PhD", "Jane Doe", "Ann Advisor"]}
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert len(people) == 2
    assert people[0] is cached
    assert cached.full_name == "Jane Doe PhD"
    assert cached.linkedin_id == "jane-123"
    assert cached.email_addresses == ["jane@example.com"]
    assert cached.linkedin_profile == {"headline": "Known profile"}
    assert read_roster("acme")[0].linkedin_id == "jane-123"
    assert read_roster("acme")[0].email_addresses == ["jane@example.com"]
    discovery.LinkedInResolver.return_value.get_profiles.assert_not_called()


@pytest.mark.asyncio
async def test_named_link_connects_cached_id_and_discovered_name(discovery):
    discovery.LinkedInResolver.return_value.get_cached_persons.return_value = [
        Person(linkedin_id="jane-123", email_addresses=["jane@example.com"]),
    ]
    discovery.dataset_chat_json.return_value = {"names": ["Jane Doe"]}
    directory = dataset_location_for_domain("acme", "startups").parsed_rel
    get_storage().write_text(f"{directory}/a.md", "https://linkedin.com/in/jane-123/")
    get_storage().write_text(f"{directory}/z.md", "[Jane Doe](https://linkedin.com/in/jane-123/)")
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert len(people) == 1
    assert people[0].full_name == "Jane Doe"
    assert people[0].linkedin_id == "jane-123"
    assert people[0].email_addresses == ["jane@example.com"]


@pytest.mark.asyncio
async def test_distinct_linkedin_ids_are_not_merged(discovery):
    discovery.LinkedInResolver.return_value.get_cached_persons.return_value = [
        Person(full_name="Jane Doe", linkedin_id="jane-one"),
        Person(full_name="Jane Doe", linkedin_id="jane-two"),
    ]
    discovery.dataset_chat_json.return_value = {"names": ["Jane Doe"]}
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert {p.linkedin_id for p in people} == {"jane-one", "jane-two"}


@pytest.mark.asyncio
async def test_manual_roster_prevents_cached_person_loading(discovery):
    InsightFile("acme", "persons_in_dataset", "manual").save(
        "| full-name | linkedin-id |\n|---|---|\n| Reviewed Person | reviewed-id |\n"
    )
    people = await discovery.persons_in_dataset_as_person_objects("acme")
    assert [p.linkedin_id for p in people] == ["reviewed-id"]
    discovery.LinkedInResolver.assert_not_called()
    discovery.sync_datasets.assert_not_awaited()
    discovery.dataset_chat_json.assert_not_awaited()

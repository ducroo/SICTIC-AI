import importlib
from unittest.mock import AsyncMock

import pytest

from lib.datasets.chunking import build_chunk
from lib.infrastructure.configuration import load_repository_config
from lib.people.model import Person


@pytest.fixture
def reconciliation(mock_env, monkeypatch):
    module = importlib.import_module("skills.persons_in_dataset.reconciliation")
    monkeypatch.setattr(module, "generate_json", AsyncMock(return_value={"existing_persons": [
        {"full_name": "Jane Doe", "linkedin_id": "jane-id", "email_addresses": ["jane@example.com"]},
    ], "additional_persons": []}))
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "   "])
async def test_empty_people_are_dropped_but_sparse_identities_survive(reconciliation, name):
    reconciliation.generate_json.return_value = {"existing_persons": [], "additional_persons": [
        {"full_name": name, "linkedin_id": "", "email_addresses": []},
        {"full_name": "", "linkedin_id": "jane-id", "email_addresses": []},
        {"full_name": "", "linkedin_id": "", "email_addresses": ["ann@example.com"]},
        {"full_name": "John Smith", "linkedin_id": "", "email_addresses": []},
    ]}
    result = await reconciliation.reconcile_people([], [], startup_context="Acme", company_names=["acme"],
        config=load_repository_config("persons_in_dataset", "discovery"))
    assert [person.identifier for person in result] == ["jane-id", "ann@example.com", "john-smith"]
    reconciliation.generate_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_call_uses_compact_history_and_keeps_person_evidence(reconciliation):
    chunk = build_chunk("Jane Doe founded Acme. Contact jane@example.com", "team.md", 3, 0)
    person = Person(full_name="Jane Doe", linkedin_id="jane-id", mentions=[chunk], linkedin_profile={
        "summary": "Unrelated long biography" * 5000,
        "positions": [{"title": "Founder", "company": {"name": "Acme"}, "timePeriod": {"startDate": {"year": 2020}}}],
    })
    result = await reconciliation.reconcile_people([person], [], startup_context="Acme startup", company_names=["acme"], config=load_repository_config("persons_in_dataset", "discovery"))
    reconciliation.generate_json.assert_awaited_once()
    prompt = reconciliation.generate_json.await_args.args[0]
    assert "Startup context:\nAcme startup" in prompt
    assert "Unrelated long biography" not in prompt
    assert '"year": 2020' in prompt
    assert "Page: 3" in prompt
    assert result[0].mentions == [chunk]
    assert result[0].linkedin_profile == person.linkedin_profile


@pytest.mark.asyncio
async def test_budget_failure_happens_before_any_llm_call(reconciliation):
    config = load_repository_config("persons_in_dataset", "discovery")
    config.update(max_prompt_chars=2000, max_reconciliation_calls=1, instructions="Reconcile")
    people = [Person(full_name=f"Candidate {i}", mentions=[build_chunk("evidence " * 100, f"doc-{i}.md", 1, 0)]) for i in range(10)]
    with pytest.raises(ValueError, match="configured maximum"):
        await reconciliation.reconcile_people(people, [], startup_context="Acme", company_names=["acme"], config=config)
    reconciliation.generate_json.assert_not_awaited()


@pytest.mark.parametrize("returned_id", ["", "incorrect-id"])
def test_existing_person_recovers_candidate_id_and_metadata(reconciliation, returned_id):
    chunk = build_chunk("Jane Doe", "cv.md", 1, 0)
    candidate = Person(full_name="Jane Doe", linkedin_id="jane-id", email_addresses=["jane@example.com"], mentions=[chunk], adhoc_data={"test": {"role": "CEO"}})
    result = reconciliation._resolve_existing(Person(full_name="Jane Doe", linkedin_id=returned_id), [candidate])
    assert result[0].linkedin_id == "jane-id"
    assert result[0].email_addresses == ["jane@example.com"]
    assert result[0].mentions == [chunk]
    assert result[0].adhoc_data == candidate.adhoc_data
    result[0].email_addresses.append("extra@example.com")
    assert candidate.email_addresses == ["jane@example.com"]


def test_existing_person_without_candidate_is_discarded(reconciliation):
    assert reconciliation._resolve_existing(Person(full_name="Unknown Stranger", linkedin_id="invented-id"), [Person(full_name="Jane Doe", linkedin_id="jane-id")]) == []


def test_candidate_without_id_does_not_inherit_returned_id(reconciliation):
    result = reconciliation._resolve_existing(Person(full_name="Jane Doe", linkedin_id="invented-id"), [Person(full_name="Jane Doe")])
    assert result[0].linkedin_id == ""


def test_ambiguous_existing_retains_candidates_without_mixing_contacts(reconciliation):
    candidates = [Person(full_name="Jane Doe", linkedin_id="jane-one", email_addresses=["one@example.com"]),
                  Person(full_name="Jane Doe", linkedin_id="jane-two", email_addresses=["two@example.com"])]
    returned = Person(full_name="Jane Doe", linkedin_id="wrong-id", email_addresses=["llm@example.com"])
    result = reconciliation._resolve_existing(returned, candidates)
    assert [(p.linkedin_id, p.email_addresses) for p in result] == [("jane-one", ["one@example.com"]), ("jane-two", ["two@example.com"])]
    assert returned.linkedin_id == "wrong-id"


def test_explicit_matching_id_does_not_trigger_name_only_fallback(reconciliation):
    candidates = [Person(full_name="Jane Doe"), Person(full_name="Jane Doe", linkedin_id="jane-one"), Person(full_name="Jane Doe", linkedin_id="jane-two")]
    result = reconciliation._resolve_existing(Person(full_name="Jane Doe", linkedin_id="jane-one"), candidates)
    assert [p.linkedin_id for p in result] == ["jane-one"]


def test_response_schema_objects_are_closed_and_require_all_fields():
    schema = load_repository_config("persons_in_dataset", "discovery")["response_schema"]
    def check(value):
        if isinstance(value, dict):
            if "properties" in value:
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(value["properties"])
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(schema)


@pytest.mark.asyncio
async def test_additional_person_is_accepted_without_evidence_matching(reconciliation):
    chunk = build_chunk("Jane Doe founded Acme. jane@example.com https://linkedin.com/in/jane-id/", "team.md", 1, 0)
    reconciliation.generate_json.return_value = {"existing_persons": [], "additional_persons": [{"full_name": "Additional Name", "linkedin_id": "additional-id", "email_addresses": ["ADDITIONAL@example.com"]}]}
    result = await reconciliation.reconcile_people([], [chunk], startup_context="Acme", company_names=["acme"], config=load_repository_config("persons_in_dataset", "discovery"))
    assert result[0].full_name == "Additional Name"
    assert result[0].linkedin_id == "additional-id"
    assert result[0].email_addresses == ["additional@example.com"]
    assert "reviewer" not in reconciliation.generate_json.await_args.kwargs


@pytest.mark.asyncio
async def test_lists_merge_duplicate_ids_but_preserve_distinct_ids(reconciliation):
    reconciliation.generate_json.return_value["additional_persons"] = [
        {"full_name": "Jane Doe", "linkedin_id": "jane-id", "email_addresses": []},
        {"full_name": "Jane Doe", "linkedin_id": "other-id", "email_addresses": []}]
    result = await reconciliation.reconcile_people([Person(full_name="Jane Doe", linkedin_id="jane-id")], [], startup_context="Acme", company_names=["acme"], config=load_repository_config("persons_in_dataset", "discovery"))
    assert [p.linkedin_id for p in result] == ["jane-id", "other-id"]

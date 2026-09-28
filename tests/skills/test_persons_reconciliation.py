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
async def test_linkedin_overflow_fails_before_any_llm_call(reconciliation, monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "100")
    monkeypatch.setattr(reconciliation, "token_counter", lambda **kwargs: 100 if "mandatory-person" in kwargs.get("text", "") else 1)
    config = load_repository_config("persons_in_dataset", "discovery")
    people = [Person(linkedin_id="mandatory-person")]
    with pytest.raises(ValueError, match="LinkedIn candidates exceed"):
        await reconciliation.reconcile_people(people, [], startup_context="Acme", company_names=["acme"], config=config)
    reconciliation.generate_json.assert_not_awaited()


def test_one_prompt_prioritizes_linkedin_then_summed_document_weights(reconciliation, monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "10000")
    # Exact, deterministic character-sized tokens isolate the selection contract.
    monkeypatch.setattr(reconciliation, "token_counter", lambda **kw: len(kw["text"]) if "text" in kw else len(kw["messages"][0]["content"]))
    config = load_repository_config("persons_in_dataset", "discovery")
    config["instructions"] = "Select people"
    website = build_chunk("Candidates", "website/team.md", 1, 0)
    dedicated = build_chunk("Contact", "contact.md", 1, 0)
    email = Person(email_addresses=["weighted@example.com"], mentions=[website, dedicated])
    weak = [Person(full_name=f"Candidate {i}", mentions=[website]) for i in range(100)]
    linkedin = Person(linkedin_id="mandatory-id")
    people = [*weak, email, linkedin]
    prompt, selected = reconciliation._prepare_prompt(people, [], startup_context="Acme", company_names=["acme"], config=config)
    assert selected[:2] == [linkedin, email]
    assert len(selected) < len(people)
    assert '"mandatory-id"' in prompt
    assert people[-1] is linkedin  # caller ordering is unchanged
    schema_overhead = reconciliation.schema_prompt_block(config["response_schema"]) + "\n\n"
    import json
    assert len(schema_overhead + prompt) + len(json.dumps(reconciliation.json_schema_response_format(config["response_schema"]))) <= 7500


@pytest.mark.asyncio
async def test_more_than_thirty_candidates_fit_in_one_request(reconciliation, monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "262144")
    people = [Person(full_name=f"Candidate {i}") for i in range(100)]
    config = load_repository_config("persons_in_dataset", "discovery")
    prompt, selected = reconciliation._prepare_prompt(people, [], startup_context="Acme", company_names=["acme"], config=config)
    assert len(selected) == 100
    await reconciliation.reconcile_people(people, [], startup_context="Acme", company_names=["acme"], config=config)
    reconciliation.generate_json.assert_awaited_once()


def test_mandatory_context_overflow(reconciliation, monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "1")
    with pytest.raises(ValueError, match="Startup/team context"):
        reconciliation._prepare_prompt([], [], startup_context="Acme", company_names=["acme"], config=load_repository_config("persons_in_dataset", "discovery"))


@pytest.mark.parametrize("name,email,noisy", [
    ("Christoph Messmer", "c.messmer@ai-on.ai", "Christoph Messmer"),
    ("Gianina Viglino-Caviezel", "g.viglino@ai-on.ai", "Gianina Viglino-CaviezelCo-Founder"),
    ("Karim Itani", "k.itani@ai-on.ai", "Karim Itani Co-Founder"),
])
def test_complementary_fragments_enrich_one_clean_person(reconciliation, name, email, noisy):
    name_chunk = build_chunk(name, "team.md", 1, 0)
    email_chunk = build_chunk(email, "contact.md", 1, 0)
    candidates = [Person(full_name=noisy, mentions=[name_chunk]),
                  Person(email_addresses=[email], mentions=[email_chunk])]
    result = reconciliation._enrich_person(Person(full_name=name, email_addresses=[email]), candidates)
    assert result.full_name == name
    assert result.email_addresses == [email]
    assert {c.chunk_id for c in result.mentions} == {name_chunk.chunk_id, email_chunk.chunk_id}
    assert candidates[0].email_addresses == []
    assert candidates[1].full_name == ""
    result.mentions.clear()
    assert candidates[0].mentions == [name_chunk]


def test_unmatched_returned_person_is_preserved(reconciliation):
    person = Person(full_name="New Person", linkedin_id="new-id")
    result = reconciliation._enrich_person(person, [Person(full_name="Jane Doe")])
    assert result == person
    assert result is not person


def test_matching_candidate_enriches_missing_id_and_metadata(reconciliation):
    candidate = Person(full_name="Jane Doe", linkedin_id="jane-id",
                       adhoc_data={"test": {"role": "CEO"}})
    result = reconciliation._enrich_person(Person(full_name="Jane Doe"), [candidate])
    assert result.linkedin_id == "jane-id"
    assert result.adhoc_data == candidate.adhoc_data
    result.adhoc_data["test"]["role"] = "CTO"
    assert candidate.adhoc_data["test"]["role"] == "CEO"


def test_conflicting_ids_do_not_override_returned_identity(reconciliation):
    candidates = [Person(full_name="Jane Doe", linkedin_id="jane-one", email_addresses=["one@example.com"]),
                  Person(full_name="Jane Doe", linkedin_id="jane-two", email_addresses=["two@example.com"])]
    result = reconciliation._enrich_person(Person(full_name="Jane Doe", linkedin_id="returned-id"), candidates)
    assert result.linkedin_id == "returned-id"
    assert result.email_addresses == []


def test_multiple_candidate_ids_are_not_arbitrarily_assigned(reconciliation):
    candidates = [Person(full_name="Jane Doe", linkedin_id="jane-one", email_addresses=["one@example.com"]),
                  Person(full_name="Jane Doe", linkedin_id="jane-two", email_addresses=["two@example.com"]),
                  Person(full_name="Jane Doe", email_addresses=["supported@example.com"])]
    result = reconciliation._enrich_person(Person(full_name="Jane Doe"), candidates)
    assert result.linkedin_id == ""
    assert result.email_addresses == ["supported@example.com"]


def test_exact_id_also_collects_idless_fragments(reconciliation):
    chunk = build_chunk("jane@example.com", "contact.md", 1, 0)
    candidates = [Person(full_name="Jane Doe", linkedin_id="jane-one"),
                  Person(full_name="Jane Doe", linkedin_id="jane-two", email_addresses=["other@example.com"]),
                  Person(email_addresses=["jane@example.com"], mentions=[chunk])]
    result = reconciliation._enrich_person(Person(full_name="Jane Doe", linkedin_id="jane-one",
                                                  email_addresses=["jane@example.com"]), candidates)
    assert result.linkedin_id == "jane-one"
    assert result.email_addresses == ["jane@example.com"]
    assert result.mentions == [chunk]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["existing_persons", "additional_persons"])
async def test_returned_people_are_the_only_roster_members(reconciliation, group):
    chunk = build_chunk("Christoph Messmer: c.messmer@ai-on.ai", "team.md", 1, 0)
    candidates = [Person(full_name="Christoph Messmer", mentions=[chunk]),
                  Person(email_addresses=["c.messmer@ai-on.ai"]), Person(full_name="Unselected Person")]
    response = {"existing_persons": [], "additional_persons": []}
    response[group] = [{"full_name": "Christoph Messmer", "linkedin_id": "", "email_addresses": ["c.messmer@ai-on.ai"]}]
    reconciliation.generate_json.return_value = response
    result = await reconciliation.reconcile_people(candidates, [], startup_context="Aion", company_names=["aion"],
        config=load_repository_config("persons_in_dataset", "discovery"))
    assert len(result) == 1
    assert result[0].full_name == "Christoph Messmer"
    assert result[0].email_addresses == ["c.messmer@ai-on.ai"]
    assert result[0].mentions == [chunk]


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

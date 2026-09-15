from types import SimpleNamespace

import pytest

from lib.datasets.chunking import build_chunk
from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.source import iter_parsed_chunks
from lib.people.extraction import PersonExtractor, merge_person, rank_people_by_document_weight
from lib.people.model import Person
from lib.storage import get_storage


class FakeNER:
    def pipe(self, inputs, **kwargs):
        for text, chunk in inputs:
            entities = [SimpleNamespace(text=name, label_="PER") for name in ("Jane Doe", "Ann Advisor") if name in text]
            yield SimpleNamespace(ents=entities), chunk


def test_document_weight_divides_one_between_names_not_occurrences_or_contacts():
    shared = build_chunk("Jane Doe and Ann Advisor", "shared.md", 1, 0)
    repeated = build_chunk("Jane Doe again", "shared.md", 2, 0)
    dedicated = build_chunk("Ann Advisor", "ann.md", 1, 0)
    jane = Person(full_name="Jane Doe", mentions=[shared, repeated, shared])
    ann = Person(full_name="Ann Advisor", mentions=[shared, dedicated])
    email = Person(email_addresses=["hello@example.com"], mentions=[shared])
    ranked = rank_people_by_document_weight([jane, ann, email])
    assert ranked == [(ann, 1.5), (jane, 0.5)]
    assert ranked[0][0] is ann
    assert jane.mentions == [shared, repeated, shared]


def test_weighting_uses_existing_fuzzy_merge_and_keeps_distinct_linkedin_ids():
    one = build_chunk("Jane Doe", "one.md", 1, 0)
    two = build_chunk("Jane Doe, PhD", "two.md", 1, 0)
    people = [Person(full_name="Jane Doe", linkedin_id="jane-one", mentions=[one])]
    merge_person(people, Person(full_name="Jane Doe, PhD", mentions=[two]))
    merge_person(people, Person(full_name="Jane Doe", linkedin_id="jane-two", mentions=[one]))
    assert len(people) == 2
    ranked = rank_people_by_document_weight(people)
    assert [(p.linkedin_id, score) for p, score in ranked] == [("jane-one", 1.5), ("jane-two", 0.5)]


def test_document_weight_ties_are_deterministic_and_empty_input_is_supported():
    ann, jane = Person(full_name="Ann Advisor"), Person(full_name="Jane Doe")
    assert rank_people_by_document_weight([jane, ann]) == [(ann, 0), (jane, 0)]
    assert rank_people_by_document_weight([]) == []


def test_all_chunks_are_scanned_and_distinct_same_page_evidence_survives():
    chunks = [build_chunk(f"Paragraph {i}: Jane Doe works at Acme.", "team.md", 1, 0) for i in range(75)]
    people = PersonExtractor("fake", batch_size=8, nlp=FakeNER()).extract(chunks)
    assert len(people) == 1
    assert people[0].full_name == "Jane Doe"
    assert len(people[0].mentions) == 75


def test_named_link_connects_identity_but_unassociated_email_remains_separate():
    chunk = build_chunk("[Jane Doe](https://linkedin.com/in/jane-doe/)\nAnn Advisor ann@example.com", "team.md", 2, 0)
    people = PersonExtractor("fake", batch_size=8, nlp=FakeNER()).extract([chunk])
    jane = next(person for person in people if person.full_name == "Jane Doe")
    assert jane.linkedin_id == "jane-doe"
    assert not jane.email_addresses
    assert next(person for person in people if person.email_addresses).full_name == ""


def test_urls_and_emails_survive_no_ner_entities():
    chunk = build_chunk("https://ch.linkedin.com/in/hidden-id/\nhttps://linkedin.com/company/acme/\nFIRST@example.com", "contacts.md", 1, 0)
    people = PersonExtractor("fake", batch_size=8, nlp=FakeNER()).extract([chunk])
    assert {person.linkedin_id for person in people} == {"", "hidden-id"}
    assert [email for person in people for email in person.email_addresses] == ["first@example.com"]


def test_named_link_connects_cached_id_and_name_without_crossing_ids():
    people = [Person(full_name="Jane Doe"), Person(linkedin_id="jane-id", email_addresses=["jane@example.com"])]
    merge_person(people, Person(full_name="Jane Doe", linkedin_id="jane-id"))
    assert len(people) == 1
    assert people[0].email_addresses == ["jane@example.com"]
    merge_person(people, Person(full_name="Jane Doe", linkedin_id="different-id"))
    assert len(people) == 2


def test_parsed_scan_uses_source_inventory_and_page_markers(mock_env):
    location = dataset_location_for_domain("acme", "startups")
    storage = get_storage()
    storage.write_text(f"{location.raw_rel}/team.pdf", "source-placeholder")
    storage.write_text(f"{location.parsed_rel}/team.pdf.md", "<!-- sictic-page:7 -->\nJane Doe works at Acme.")
    storage.write_text(f"{location.parsed_rel}/stale.md", "Stale Person")
    chunks = list(iter_parsed_chunks("acme"))
    assert len(chunks) == 1
    assert chunks[0].document_name == "team.pdf"
    assert chunks[0].page_number == 7


def test_spacy_multilingual_model_extracts_documented_people():
    pytest.importorskip("xx_ent_wiki_sm")
    examples = [
        ("employment.md", "Employment agreement: Patrick Schuler is employed by Acme AG as Chief Technology Officer.", "Patrick Schuler"),
        ("team.md", "Our founders are Urs Gubser and Samuel Cheng.", "Urs Gubser"),
        ("vertrag.md", "Arbeitsvertrag: Anna Müller arbeitet als Ingenieurin bei Acme AG.", "Anna Müller"),
        ("contrat.md", "Marie Dupont est ingénieure chez Acme SA.", "Marie Dupont"),
    ]
    people = PersonExtractor("xx_ent_wiki_sm", batch_size=8).extract(
        build_chunk(text, filename, 1, 0) for filename, text, _ in examples
    )
    found = {person.full_name for person in people}
    expected = {name for _, _, name in examples}
    assert expected <= found, (expected - found, found)

from copy import deepcopy

from lib.people.linkedin import clean_linkedin_payload, find_cached_person
from lib.people.model import Person


def test_explicit_linkedin_id_never_fuzzy_matches_different_cached_id():
    requested = Person(
        full_name="Patrick Schuler",
        linkedin_id="patrick-schuler-requested",
    )
    cached = [
        Person(
            full_name="Patrick Schuler",
            linkedin_id="different-patrick",
            linkedin_profile={"headline": "Wrong person"},
        )
    ]

    assert find_cached_person(requested, cached) is None


def test_email_match_precedes_fuzzy_name_matching():
    requested = Person(
        full_name="P. Schuler",
        email_addresses=["patrick@example.com"],
    )
    expected = Person(
        full_name="Patrick Schuler",
        linkedin_id="schulerp",
        email_addresses=["patrick@example.com"],
    )
    other = Person(
        full_name="P. Schuler",
        linkedin_id="other",
    )

    assert find_cached_person(requested, [other, expected]) is expected


def test_linkedin_cleaning_removes_links_and_technical_fields():
    payload = {
        "fullName": "Jane Doe",
        "profileUrl": "https://www.linkedin.com/in/jane-doe/",
        "headline": "Founder at Example https://example.com/team",
        "summary": "Built [Example](https://example.com) in Zurich",
        "profileImage": "https://cdn.example.com/jane.jpg",
        "entityUrn": "urn:li:fsd_profile:123",
        "tracking": "urn:li:tracking:456",
        "multiLocaleHeadline": {"en_US": "Founder"},
        "peopleAlsoViewed": [{"fullName": "Another Person"}],
        "publications": [
            {"title": "Useful research", "url": "https://example.com/paper"}
        ],
    }
    original = deepcopy(payload)

    cleaned = clean_linkedin_payload(payload)

    assert payload == original
    assert cleaned == {
        "fullName": "Jane Doe",
        "headline": "Founder at Example",
        "summary": "Built Example in Zurich",
        "publications": [{"title": "Useful research"}],
    }

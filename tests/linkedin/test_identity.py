from lib.linkedin.identity import find_cached_person
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

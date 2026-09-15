from lib.people.model import Person, extract_email_addresses
from lib.datasets.chunking import build_chunk
import pytest


def test_exact_id_selection_excludes_earlier_name_and_email_matches():
    requested = Person(full_name="Mathieu Barthet", linkedin_id="mathieu-id", email_addresses=["mathieu@example.com"])
    name = Person(full_name="Mathieu Barthet")
    email = Person(email_addresses=["mathieu@example.com"])
    exact = Person(full_name="M. Barthet", linkedin_id="mathieu-id")
    other = Person(full_name="Mathieu Barthet", linkedin_id="other-id")
    candidates = [name, email, other, exact]
    assert requested.find_matches(candidates) == [exact]
    assert requested.find_best_match(candidates) is exact
    assert requested.find_matches(candidates, threshold=101) == []


def test_find_matches_preserves_same_id_records_and_fallback_tie_order():
    first = Person(full_name="Jane Doe", linkedin_id="jane-id")
    second = Person(full_name="Jane", linkedin_id="jane-id")
    assert first.find_matches([second, first]) == [second, first]
    name_only = Person(full_name="Jane Doe")
    alternative = Person(full_name="Jane Doe", linkedin_id="other-id")
    assert name_only.find_matches([first, alternative]) == [first, alternative]
    assert name_only.find_best_match([first, alternative]) is first


def test_find_matches_does_not_drop_conflicting_id_implicitly():
    requested = Person(full_name="Jane Doe", linkedin_id="jane-id")
    assert requested.find_matches([Person(full_name="Jane Doe", linkedin_id="other-id")]) == []
    assert requested.find_best_match([]) is None


@pytest.mark.parametrize("profile", [{"fullName": "Mathieu Barthet"}, {"firstName": "Mathieu", "lastName": "Barthet"}])
def test_merge_prefers_structured_linkedin_name_and_keeps_it_on_later_merges(profile):
    person = Person(full_name="Mathieu Barthet Co-Founder")
    candidate = Person(full_name="M. Barthet", linkedin_id="mathieu-id", linkedin_profile=profile)
    person.merge(candidate)
    assert person.full_name == "Mathieu Barthet"
    person.merge(Person(full_name="Mathieu Barthet Some Longer Extracted Text"))
    assert person.full_name == "Mathieu Barthet"
    assert candidate.full_name == "M. Barthet"


def test_merge_without_profile_name_retains_existing_longer_name_policy():
    person = Person(full_name="M. Barthet", linkedin_id="mathieu-id", linkedin_profile={"headline": "Researcher"})
    person.merge(Person(full_name="Mathieu Barthet"))
    assert person.full_name == "Mathieu Barthet"


def test_mismatched_profile_payload_cannot_override_name():
    person = Person(full_name="Jane Doe", linkedin_id="jane-id", linkedin_profile={"publicIdentifier": "other-id", "fullName": "Different Person"})
    person.merge(Person(full_name="Jane"))
    assert person.full_name == "Jane Doe"


def test_person_linkedin_id_is_hard_identity_boundary():
    left = Person(full_name="Urs Gubser", linkedin_id="urs-gubser", email_addresses=["urs@example.com"])
    right = Person(full_name="Urs Gubser", linkedin_id="other-urs", email_addresses=["urs@example.com"])

    assert left.match_score(right) == 0
    assert not left.matches(right)


def test_person_matches_by_email_without_linkedin_id():
    left = Person(full_name="Urs Gubser", email_addresses=["URS@GUBSER.CH"])
    right = Person(email_addresses=["urs@gubser.ch"])

    assert left.matches(right)


def test_person_matches_name_against_email_local_part():
    left = Person(full_name="Urs Gubser")
    right = Person(email_addresses=["urs.gubser@example.com"])

    assert left.matches(right)


def test_person_merge_deduplicates_normalized_email_addresses():
    left = Person(full_name="Urs Gubser", email_addresses=["urs@gubser.ch"])
    right = Person(email_addresses=["URS@GUBSER.CH", "urs.gubser@investor.sictic.ch"])

    left.merge(right)

    assert left.email_addresses == ["urs@gubser.ch", "urs.gubser@investor.sictic.ch"]


def test_person_merge_fills_missing_linkedin_id_from_matching_person():
    left = Person(full_name="Samuel Cheng")
    right = Person(full_name="Samuel Cheng", linkedin_id="samuel-cheng")

    left.merge(right)

    assert left.linkedin_id == "samuel-cheng"


def test_person_merge_preserves_distinct_mentions_on_the_same_page():
    founder = build_chunk("Jane Doe founded Acme.", "team.md", 1, 0)
    role = build_chunk("Jane Doe is the CTO.", "team.md", 1, 0)
    person = Person(full_name="Jane Doe", mentions=[founder])

    person.merge(Person(full_name="Jane Doe", mentions=[role]))

    assert person.mentions == [founder, role]


def test_person_merge_deduplicates_mentions_by_chunk_identity():
    founder = build_chunk("Jane Doe founded Acme.", "team.md", 1, 0)
    retrieved_again = founder.model_copy(update={"score": 0.9})
    role = build_chunk("Jane Doe is the CTO.", "team.md", 1, 0)
    person = Person(full_name="Jane Doe", mentions=[founder])
    candidate = Person(full_name="Jane Doe", mentions=[retrieved_again, role, role])

    person.merge(candidate)
    person.merge(candidate)

    assert person.mentions == [founder, role]


def test_extract_email_addresses_recursively_scans_linkedin_payloads():
    payload = {
        "contact": {"primary": "mailto:URS@GUBSER.CH"},
        "nested": [{"text": "Reach me at urs.gubser@investor.sictic.ch"}],
    }

    assert extract_email_addresses(payload) == [
        "urs@gubser.ch",
        "urs.gubser@investor.sictic.ch",
    ]


def test_extract_email_addresses_ignores_non_email_linkedin_text():
    payload = {
        "fullName": "Urs Gubser",
        "headline": "Investor and entrepreneur",
        "summary": "Long professional biography without contact information.",
        "experience": [{"description": "Built and scaled several companies."}],
    }

    assert extract_email_addresses(payload) == []

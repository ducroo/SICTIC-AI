from lib.models.person import Person, extract_email_addresses


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


def test_extract_email_addresses_recursively_scans_linkedin_payloads():
    payload = {
        "contact": {"primary": "mailto:URS@GUBSER.CH"},
        "nested": [{"text": "Reach me at urs.gubser@investor.sictic.ch"}],
    }

    assert extract_email_addresses(payload) == [
        "urs@gubser.ch",
        "urs.gubser@investor.sictic.ch",
    ]

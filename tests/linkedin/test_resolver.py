from lib.linkedin.resolver import LinkedInResolver
from lib.people.model import Person


def test_cached_profile_enriches_existing_person():
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.cache = {
        "schulerp": Person(
            full_name="Patrick S.",
            linkedin_id="schulerp",
            email_addresses=["linkedin@example.com"],
            linkedin_profile={"firstName": "Patrick", "lastName": "S."},
        )
    }

    person = Person(
        full_name="Patrick Schuler",
        linkedin_id="schulerp",
        email_addresses=["patrick@example.com"],
    )
    resolved = resolver.get_profiles([person])

    assert resolved == [person]
    assert person.full_name == "Patrick Schuler"
    assert person.linkedin_profile == {"firstName": "Patrick", "lastName": "S."}
    assert person.email_addresses == [
        "patrick@example.com",
        "linkedin@example.com",
    ]

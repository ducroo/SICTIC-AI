from unittest.mock import MagicMock

from lib.adapters.linkedin import LinkedInAdapter
from lib.models.person import Person


def test_cached_profile_enriches_existing_person():
    adapter = LinkedInAdapter.__new__(LinkedInAdapter)
    adapter.cache = {
        "schulerp": Person(
            full_name="Patrick S.",
            linkedin_id="schulerp",
            email_addresses=["linkedin@example.com"],
            linkedin_profile={"firstName": "Patrick", "lastName": "S."},
        )
    }
    adapter.fuzz_index = []
    adapter.registry = {}
    adapter._save_registry = MagicMock()

    person = Person(
        full_name="Patrick Schuler",
        linkedin_id="schulerp",
        email_addresses=["patrick@example.com"],
    )
    resolved = adapter.get_profiles([person])

    assert resolved == [person]
    assert person.full_name == "Patrick Schuler"
    assert person.linkedin_profile == {"firstName": "Patrick", "lastName": "S."}
    assert person.email_addresses == [
        "patrick@example.com",
        "linkedin@example.com",
    ]

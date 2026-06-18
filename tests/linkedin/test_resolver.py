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


def test_cached_profile_matches_unicode_normalized_linkedin_id():
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.cache = {
        "florian-lösch-9529a856": Person(
            full_name="Florian Lösch",
            linkedin_id="florian-lösch-9529a856",
            linkedin_profile={"fullName": "Florian Lösch"},
        )
    }

    person = Person(linkedin_id="florian-lösch-9529a856")
    resolved = resolver.get_profiles([person])

    assert resolved == [person]
    assert person.linkedin_profile == {"fullName": "Florian Lösch"}


class _FakeRegistry:
    def __init__(self):
        self.marked = []

    def find(self, *_args, **_kwargs):
        return None

    def upsert(self, *_args, **_kwargs):
        return None

    def mark_status(self, linkedin_id, status):
        self.marked.append((linkedin_id, status))


class _FakeApify:
    def __init__(self):
        self.calls = []

    def run_actor(self, *, actor_id, run_input):
        self.calls.append((actor_id, run_input))
        return []


def test_linkedin_scrape_uses_profile_urls_input():
    apify = _FakeApify()
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.dataset_name = "example"
    resolver.cache = {}
    resolver.registry_store = _FakeRegistry()
    resolver._apify_factory = lambda: apify

    resolver.get_profiles([Person(linkedin_id="jane-doe")])

    assert apify.calls == [
        (
            "dev_fusion/Linkedin-Profile-Scraper",
            {"profileUrls": ["https://www.linkedin.com/in/jane-doe/"]},
        )
    ]

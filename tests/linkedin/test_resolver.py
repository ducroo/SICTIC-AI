import pytest

from lib.infrastructure.errors import InfrastructureError
from lib.people.linkedin import LinkedInResolver
from lib.people.model import Person


class _FakeRegistry:
    def __init__(self):
        self.entries = {}

    def find(self, _key, linkedin_id="", _full_name=""):
        entry = self.entries.get(linkedin_id)
        return (linkedin_id, entry) if entry else None

    def upsert(self, _key, **kwargs):
        linkedin_id = kwargs["linkedin_id"]
        existing = self.entries.get(linkedin_id, {})
        self.entries[linkedin_id] = {
            **existing,
            "datasets": sorted(
                set(existing.get("datasets", [])) | {kwargs["dataset"]}
            ),
            "full_name": kwargs["full_name"],
            "linkedin_id": linkedin_id,
            "status": kwargs["status"],
        }

    def load(self):
        return self.entries

    def set_status(self, linkedin_ids, status):
        for linkedin_id in linkedin_ids:
            self.entries[linkedin_id]["status"] = status

    def remove_identity(self, linkedin_id):
        self.entries.pop(linkedin_id, None)


class _FakeProfileStore:
    def load_all(self):
        return {}


class _FakeApify:
    def __init__(self):
        self.calls = []

    def start_actor(self, *, actor_id, run_input):
        self.calls.append(("start", actor_id, run_input))
        return "run-1"

    def wait_for_run(self, run_id, wait_seconds):
        self.calls.append(("wait", run_id, wait_seconds))

    def get_run(self, run_id):
        self.calls.append(("get", run_id))
        return {"id": run_id, "status": "RUNNING"}


class _RefusingApify(_FakeApify):
    def start_actor(self, *, actor_id, run_input):
        self.calls.append(("start", actor_id, run_input))
        raise RuntimeError("subscription required")


class _CompletedApify(_FakeApify):
    def __init__(self, payloads):
        super().__init__()
        self.payloads = payloads

    def get_run(self, run_id):
        self.calls.append(("get", run_id))
        return {
            "id": run_id,
            "status": "SUCCEEDED",
            "defaultDatasetId": "dataset-1",
        }

    def run_items(self, run):
        self.calls.append(("items", run["id"]))
        return self.payloads

    def delete_run(self, run_id):
        self.calls.append(("delete", run_id))


def _resolver(apify, registry=None):
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.dataset_name = "example"
    resolver.profiles = {}
    resolver.registry = registry or _FakeRegistry()
    resolver._apify_factory = lambda: apify
    resolver.wait_seconds = 60
    resolver.profile_store = _FakeProfileStore()
    return resolver


def test_cached_profile_enriches_existing_person():
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.profiles = {
        "schulerp": {
            "fullName": "Patrick S.",
            "email": "linkedin@example.com",
        }
    }
    person = Person(
        full_name="Patrick Schuler",
        linkedin_id="schulerp",
        email_addresses=["patrick@example.com"],
    )

    assert resolver.get_profiles([person]) == [person]
    assert person.full_name == "Patrick Schuler"
    assert person.linkedin_profile["fullName"] == "Patrick S."
    assert person.email_addresses == [
        "patrick@example.com",
        "linkedin@example.com",
    ]


def test_cached_profile_matches_unicode_normalized_linkedin_id():
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.profiles = {
        "florian-lösch-9529a856": {"fullName": "Florian Lösch"}
    }
    person = Person(linkedin_id="florian-lösch-9529a856")

    assert resolver.get_profiles([person]) == [person]
    assert person.linkedin_profile == {"fullName": "Florian Lösch"}


def test_linkedin_scrape_uses_one_batch_and_records_run_id():
    apify = _FakeApify()
    resolver = _resolver(apify)

    with pytest.raises(InfrastructureError, match="still being processed"):
        resolver.get_profiles([Person(full_name="Jane Doe", linkedin_id="jane-doe")])

    assert apify.calls == [
        (
            "start",
            "dev_fusion/Linkedin-Profile-Scraper",
            {"profileUrls": ["https://www.linkedin.com/in/jane-doe/"]},
        ),
        ("wait", "run-1", 60),
        ("get", "run-1"),
    ]
    assert resolver.registry.entries["jane-doe"]["status"] == "run-1"


def test_refused_apify_batch_marks_profile_failed():
    resolver = _resolver(_RefusingApify())

    with pytest.raises(InfrastructureError, match="manual retrieval"):
        resolver.get_profiles([Person(linkedin_id="jane-doe")])

    assert resolver.registry.entries["jane-doe"]["status"] == "failed"


def test_apify_initialization_failure_marks_profile_failed():
    resolver = _resolver(_FakeApify())

    def unavailable_apify():
        raise RuntimeError("APIFY_KEY is unavailable")

    resolver._apify_factory = unavailable_apify
    with pytest.raises(InfrastructureError, match="manual retrieval"):
        resolver.get_profiles([Person(linkedin_id="jane-doe")])

    assert resolver.registry.entries["jane-doe"]["status"] == "failed"


def test_explicit_missing_profile_is_marked_not_found():
    apify = _CompletedApify(
        [{"publicIdentifier": "missing-person", "not_found": True}]
    )
    resolver = _resolver(apify)
    person = Person(linkedin_id="missing-person")

    assert resolver.get_profiles([person]) == [person]
    assert resolver.registry.entries["missing-person"]["status"] == "not_found"
    assert ("delete", "run-1") in apify.calls


def test_generic_profile_error_is_failed_not_not_found():
    apify = _CompletedApify(
        [{"publicIdentifier": "jane-doe", "error": "quota exceeded"}]
    )
    resolver = _resolver(apify)

    with pytest.raises(InfrastructureError, match="manual retrieval"):
        resolver.get_profiles([Person(linkedin_id="jane-doe")])

    assert resolver.registry.entries["jane-doe"]["status"] == "failed"


def test_existing_runs_are_checked_after_waiting_for_new_batch():
    apify = _FakeApify()
    registry = _FakeRegistry()
    registry.entries["older-person"] = {
        "datasets": ["older-dataset"],
        "full_name": "Older Person",
        "linkedin_id": "older-person",
        "status": "older-run",
    }
    resolver = _resolver(apify, registry)

    with pytest.raises(InfrastructureError, match="still being processed"):
        resolver.get_profiles([Person(linkedin_id="new-person")])

    wait_index = apify.calls.index(("wait", "run-1", 60))
    get_indexes = [
        index for index, call in enumerate(apify.calls) if call[0] == "get"
    ]
    assert get_indexes
    assert all(wait_index < index for index in get_indexes)


def test_blank_linkedin_id_is_not_registered_or_scraped():
    resolver = LinkedInResolver.__new__(LinkedInResolver)
    resolver.profiles = {}
    person = Person(
        full_name="Samuel Cheng",
        linkedin_id="",
        email_addresses=["srcheng@gmail.com"],
    )

    assert resolver.get_profiles([person]) == [person]

from copy import deepcopy

from lib.people.linkedin.evidence import condense_profile
from lib.people.linkedin.search import search_people
from lib.people.model import Person
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind


def test_search_retains_successes_around_failed_queries(mocker):
    search = mocker.Mock()
    error = InfrastructureError("Busy", kind=InfrastructureErrorKind.RESOURCE_BUSY, provider="apify", operation="run_actor")
    search.search.side_effect = [
        [{"title": "Jane", "snippet": "Founder", "link": "https://linkedin.com/in/jane-id"}],
        error,
        [{"title": "John", "snippet": "Founder", "link": "https://linkedin.com/in/john-id"}],
    ]
    failures = []
    people = search_people("Acme", [], queries=["first", "second", "third"], num_results=10,
                           search=search, on_error=failures.append)
    assert [person.linkedin_id for person in people] == ["jane-id", "john-id"]
    assert failures == [error]


def test_condensation_keeps_all_jobs_and_matching_descriptions_without_mutation():
    payload = {
        "headline": "Founder at Acme",
        "about": "Long unrelated biography" * 2000,
        "experiences": [
            {"companyName": "Acme AG", "title": "Founder", "startDate": "2020", "endDate": None,
             "description": "Founded Acme and built its products. " * 100},
            {"companyName": "Other AG", "title": "Engineer", "startDate": "2010", "endDate": "2019",
             "description": "Long previous job" * 2000},
        ],
    }
    original = deepcopy(payload)
    person = Person(full_name="Jane Doe", linkedin_id="jane-doe", linkedin_profile=payload)
    compact = condense_profile(person, company_names=["acme"], description_chars=50)
    jobs = compact["employment_history"]["experiences"]
    assert len(jobs) == 2
    assert jobs[0]["title"] == "Founder"
    assert len(jobs[0]["description"]) == 50
    assert jobs[1]["endDate"] == "2019"
    assert "description" not in jobs[1]
    assert "about" not in compact
    assert payload == original


def test_condensation_preserves_nested_dates_and_grouped_positions():
    person = Person(linkedin_profile={"positions": [{"company": {"name": "Acme"},
        "positions": [{"title": "CTO", "startDate": {"year": 2020, "month": 2}}]}]})
    compact = condense_profile(person, company_names=["acme"], description_chars=30)
    assert compact["employment_history"]["positions"][0]["positions"][0]["startDate"] == {"year": 2020, "month": 2}


def test_search_returns_unverified_ids_with_provenance(mocker):
    search = mocker.Mock()
    search.search.return_value = [{"title": "Jane Doe - Acme", "link": "https://linkedin.com/in/jane-id/", "snippet": "CTO at Acme"}]
    people = search_people("Acme", ["Jane Doe", "Jane Doe"], queries=['site:linkedin.com/in/ "{company}"'], num_results=10, search=search)
    assert search.search.call_count == 2
    assert all(person.linkedin_id == "jane-id" and not person.full_name for person in people)
    assert people[0].mentions[0].document_name == "https://linkedin.com/in/jane-id/"


def test_named_search_uses_supplied_template_and_deduplicates_names(mocker):
    search = mocker.Mock()
    search.search.return_value = []
    search_people("Acme", ["Jane Doe", "Jane Doe"], queries=[], num_results=7,
                  search=search, name_query='"{company}" "{name}" site:linkedin.com/in/')
    search.search.assert_called_once_with('"Acme" "Jane Doe" site:linkedin.com/in/', num_results=7)


def test_condensation_handles_stored_timeperiod_and_current_position_shapes():
    person = Person(linkedin_profile={
        "positions": [{"company": {"name": "Acme"}, "positions": [
            {"title": "CTO", "timePeriod": {"startDate": {"year": 2020}, "endDate": {"year": 2024}}}
        ]}],
        "currentPosition": [{"companyName": "Other", "dateRange": {"start": {"year": 2025}}}],
    })
    history = condense_profile(person, company_names=["Acme"], description_chars=50)["employment_history"]
    assert history["positions"][0]["positions"][0]["timePeriod"]["endDate"] == {"year": 2024}
    assert history["currentPosition"][0]["dateRange"]["start"] == {"year": 2025}

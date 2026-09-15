from copy import deepcopy

from lib.people.linkedin.evidence import condense_profile
from lib.people.linkedin.search import search_people
from lib.people.model import Person
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind


def test_single_search_failure_is_reported_without_further_queries(mocker):
    search = mocker.Mock()
    error = InfrastructureError("Busy", kind=InfrastructureErrorKind.RESOURCE_BUSY, provider="apify", operation="run_actor")
    search.search.side_effect = error
    failures = []
    assert search_people("Acme", query='"{company}" team', num_results=10,
                         search=search, on_error=failures.append) == []
    search.search.assert_called_once_with('"Acme" team', num_results=10)
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
    people = search_people("Acme", query='site:linkedin.com/in/ "{company}"', num_results=10, search=search)
    assert search.search.call_count == 1
    assert all(person.linkedin_id == "jane-id" and not person.full_name for person in people)
    assert people[0].mentions[0].document_name == "https://linkedin.com/in/jane-id/"


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

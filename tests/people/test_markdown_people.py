import pytest
from lib.people.discovery import _parse_manual_persons_table

from lib.people import Person, markdown_table_to_person_objects


def test_markdown_table_to_people_preserves_identity_adhoc_data_and_order():
    markdown = r"""# Experts

| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |
|---|---|---|---|---|
| 1 | Nina Example | nina@example.com | https://linkedin.com/in/nina-example/ | Hardware \| SaaS |
| 2 | No Email | | no-email | Market access |
"""

    people = markdown_table_to_person_objects(
        markdown,
        tag="expert_search:avientus",
    )

    assert [person.full_name for person in people] == ["Nina Example", "No Email"]
    assert people[0].email_addresses == ["nina@example.com"]
    assert people[0].linkedin_id == "nina-example"
    assert people[0].adhoc_data["expert_search:avientus"] == {
        "rank": "1",
        "rationale": "Hardware | SaaS",
    }


def test_person_merge_combines_preferences_and_namespaced_adhoc_data():
    person = Person(
        full_name="Nina Example",
        adhoc_data={
            "expert_search:avientus": {"rank": "1"},
            "member_preferences": {"deep_dive_invitation": "standard"},
        },
    )
    person.merge(
        Person(
            email_addresses=["nina@investor.sictic.ch"],
            adhoc_data={
                "expert_search:avientus": {"rationale": "Relevant"},
                "member_preferences": {"deep_dive_invitation": "fewer"},
            },
        )
    )

    assert person.adhoc_data["member_preferences"]["deep_dive_invitation"] == "fewer"
    assert person.adhoc_data["expert_search:avientus"] == {
        "rank": "1",
        "rationale": "Relevant",
    }


@pytest.mark.parametrize("headers", [
    "full_name | linkedin_id | email_addresses",
    "full-name | linkedin-id | email-addresses",
    "fullName | linkedinId | emailAddresses",
    r"full\_name | linkedin\_id | email\_addresses",
])
def test_person_table_parser_matches_roster_identity_headers(headers):
    markdown = f"| {headers} |\n|---|---|---|\n| Jane Doe | jane-123 | jane@example.com |"
    people = markdown_table_to_person_objects(markdown, tag="review")
    assert people == _parse_manual_persons_table(markdown)
    assert people == [Person(full_name="Jane Doe", linkedin_id="jane-123", email_addresses=["jane@example.com"])]


def test_person_table_parser_accepts_emphasized_underscore_headers():
    markdown = "| **full_name** | `linkedin_id` | __email_addresses__ |\n|---|---|---|\n| Jane Doe | jane-123 | jane@example.com |"
    people = markdown_table_to_person_objects(markdown, tag="review")
    assert people[0].linkedin_id == "jane-123"
    assert people[0].full_name == "Jane Doe"
    assert people[0].email_addresses == ["jane@example.com"]

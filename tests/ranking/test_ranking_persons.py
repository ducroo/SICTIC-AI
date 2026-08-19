import pytest

from lib.people.model import Person
from skills.ranking.ranking_persons import (
    _resolve_members,
    rank_person_rows,
    ranking_persons,
)


MEMBERS = [
    Person(
        full_name="Urs Gubser",
        linkedin_id="urs-gubser",
        email_addresses=["urs@gubser.ch", "urs.gubser@investor.sictic.ch"],
    ),
    Person(
        full_name="Jane Doe",
        linkedin_id="jane-doe",
        email_addresses=["jane@sictic.ch"],
    ),
]


def test_resolve_members_uses_person_matching_for_candidates_and_optouts():
    selected = _resolve_members(
        MEMBERS,
        candidates=["urs@gubser.ch", "Jane Doe"],
        optout=["jane-doe"],
    )

    assert selected == [MEMBERS[0]]


def test_resolve_members_reports_unknown_requested_candidate():
    with pytest.raises(ValueError, match="Missing Member"):
        _resolve_members(MEMBERS, candidates=["Missing Member"], optout=None)


@pytest.mark.asyncio
async def test_rank_person_rows_uses_roster_metadata_and_linkedin_id(mock_env, mocker):
    mocker.patch(
        "skills.ranking.ranking_persons.persons_in_dataset",
        return_value=MEMBERS,
    )
    class FakeProfile:
        identifier = "urs-gubser"
        path = "investor-profile/urs-gubser-model.md"

        def content(self):
            return "Profile body without metadata headers"

    select = mocker.patch(
        "skills.ranking.ranking_persons.select_insights",
        return_value=[FakeProfile()],
    )
    mocker.patch(
        "skills.ranking.ranking_persons.ranking_top_k",
        return_value=(
            [{"id": "urs-gubser", "text": "Profile body", "rank": 1}],
            1,
        ),
    )
    mocker.patch(
        "skills.ranking.ranking_persons.ranking_rationale",
        return_value=[
            {
                "id": "urs-gubser",
                "text": "Profile body",
                "rank": 1,
                "rationale": "Strong fit.",
            }
        ],
    )

    rows = await rank_person_rows(
        source_datasets=["sictic-members"],
        skill="investor_profile",
        objective="Find experts",
        candidates=["Urs Gubser"],
        top_k=1,
    )

    select.assert_called_once_with(["sictic-members"], "investor_profile")

    assert rows == [
        {
            "rank": 1,
            "full_name": "Urs Gubser",
            "email_addresses": [
                "urs@gubser.ch",
                "urs.gubser@investor.sictic.ch",
            ],
            "linkedin_id": "urs-gubser",
            "rationale": "Strong fit.",
        }
    ]


@pytest.mark.asyncio
async def test_rank_person_rows_filters_people_before_reading_profiles(mock_env, mocker):
    mocker.patch(
        "skills.ranking.ranking_persons.persons_in_dataset",
        return_value=MEMBERS,
    )

    class FakeProfile:
        def __init__(self, identifier):
            self.identifier = identifier
            self.path = f"investor-profile/{identifier}-model.md"

        def content(self):
            if self.identifier == "jane-doe":
                raise AssertionError("excluded profile must not be read")
            return "Urs profile"

    mocker.patch(
        "skills.ranking.ranking_persons.select_insights",
        return_value=[FakeProfile("urs-gubser"), FakeProfile("jane-doe")],
    )
    ranking = mocker.patch(
        "skills.ranking.ranking_persons.ranking_top_k",
        return_value=([{"id": "urs-gubser", "text": "Urs profile", "rank": 1}], 1),
    )
    mocker.patch(
        "skills.ranking.ranking_persons.ranking_rationale",
        return_value=[
            {
                "id": "urs-gubser",
                "text": "Urs profile",
                "rank": 1,
                "rationale": "Strong fit.",
            }
        ],
    )

    await rank_person_rows(
        candidates=["Urs Gubser", "Jane Doe"],
        optout=["jane@sictic.ch"],
        top_k=1,
    )

    assert ranking.await_args.kwargs["all_profiles"] == {
        "urs-gubser": "Urs profile"
    }


@pytest.mark.asyncio
async def test_ranking_persons_renders_structured_rows_as_markdown(mock_env, mocker):
    mocker.patch(
        "skills.ranking.ranking_persons.rank_person_rows",
        return_value=[
            {
                "rank": 1,
                "full_name": "Urs Gubser",
                "email_addresses": [
                    "urs@gubser.ch",
                    "urs.gubser@investor.sictic.ch",
                ],
                "linkedin_id": "urs-gubser",
                "rationale": "Strong fit.",
            }
        ],
    )

    result = await ranking_persons(
        objective="Find experts",
        top_k=1,
    )

    assert "| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |" in result
    assert (
        "| 1 | Urs Gubser | urs@gubser.ch, urs.gubser@investor.sictic.ch | "
        "urs-gubser | Strong fit. |"
    ) in result

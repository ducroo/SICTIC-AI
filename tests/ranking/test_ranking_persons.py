import pytest

from lib.people.model import Person
from lib.datasets.models import Chunk
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
    mocker.patch(
        "skills.ranking.ranking_persons.dataset_search",
        return_value=[
            Chunk(
                chunk_id="1",
                document_name="urs-gubser-gemma4-31b-nvfp4.md",
                page_number=1,
                last_modified=0,
                text="Profile body without metadata headers",
                score=1.0,
            )
        ],
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
        dataset_name="sictic-members-investor-profile",
        objective="Find experts",
        query="expert",
        candidates=["Urs Gubser"],
        top_k=1,
    )

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
        dataset_name="sictic-members-investor-profile",
        objective="Find experts",
        query="expert",
        top_k=1,
    )

    assert "| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |" in result
    assert (
        "| 1 | Urs Gubser | urs@gubser.ch, urs.gubser@investor.sictic.ch | "
        "urs-gubser | Strong fit. |"
    ) in result

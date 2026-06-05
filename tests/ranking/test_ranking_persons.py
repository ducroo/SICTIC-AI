import pytest

from skills.dataset_chat.core.models import Chunk
from skills.ranking.ranking_persons import ranking_persons


@pytest.mark.asyncio
async def test_ranking_persons_uses_person_metadata_for_final_table(mock_env, mocker):
    mocker.patch(
        "skills.ranking.ranking_persons._resolve_candidates",
        return_value=["urs-gubser-gemma4-31b-nvfp4.md"],
    )
    mocker.patch(
        "skills.ranking.ranking_persons.dataset_search",
        return_value=[
            Chunk(
                chunk_id="1",
                document_name="urs-gubser-gemma4-31b-nvfp4.md",
                page_number=1,
                last_modified=0,
                text="\n".join(
                    [
                        "Full-name: Urs Gubser",
                        "linkedin-id: urs-gubser",
                        "Email-addresses: urs@gubser.ch, urs.gubser@investor.sictic.ch",
                        "",
                        "Profile body",
                    ]
                ),
                score=1.0,
            )
        ],
    )
    mocker.patch(
        "skills.ranking.ranking_persons.ranking_top_k",
        return_value=(
            [
                {
                    "id": "urs-gubser",
                    "text": "Profile body",
                    "rank": 1,
                }
            ],
            1,
        ),
    )
    mocker.patch(
        "skills.ranking.ranking_persons.ranking_rationale",
        return_value=[
            {
                "id": "urs-gubser",
                "full_name": "Urs Gubser",
                "linkedin_id": "urs-gubser",
                "email_addresses": ["urs@gubser.ch", "urs.gubser@investor.sictic.ch"],
                "rank": 1,
                "rationale": "Strong fit.",
            }
        ],
    )

    result = await ranking_persons(
        dataset_name="sictic-members-person-profile",
        objective="Find experts",
        query="expert",
        top_k=1,
    )

    assert "| Rank | Full Name | LinkedIn ID | Email Addresses | Ranking Rationale |" in result
    assert "| 1 | Urs Gubser | urs-gubser | urs@gubser.ch, urs.gubser@investor.sictic.ch | Strong fit. |" in result

from types import SimpleNamespace
import importlib

import pytest

from lib.insights import InsightFile
from lib.people import Person
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from skills.deep_dive_invitation.deep_dive_invitation import (
    deep_dive_invitation,
    parse_people_csv,
)


def test_parse_people_csv_creates_person_objects():
    people = parse_people_csv(
        "Jane Founder <jane@example.com>, investor@example.com, FONGIT"
    )

    assert [(person.full_name, person.email_addresses) for person in people] == [
        ("Jane Founder", ["jane@example.com"]),
        ("", ["investor@example.com"]),
        ("FONGIT", []),
    ]


@pytest.mark.asyncio
async def test_deep_dive_invitation_renders_review_only_draft(
    monkeypatch,
    mock_env,
):
    module = importlib.import_module(
        "skills.deep_dive_invitation.deep_dive_invitation"
    )
    location = dataset_location_for_domain("example-startup", "startups")
    get_storage().mkdir(location.raw_rel)
    get_storage().mkdir(location.parsed_rel)
    get_storage().mkdir(location.insights_rel)

    members = [
        Person(
            full_name="Interested Member",
            linkedin_id="interested-member",
            email_addresses=[
                "member@gmail.com",
                "member@investor.sictic.ch",
            ],
            adhoc_data={
                "member_preferences": {"deep_dive_invitation": "none"},
            },
        )
    ]
    for index in range(12):
        members.append(
            Person(
                full_name=f"Expert {index}",
                linkedin_id=f"expert-{index}",
                email_addresses=[f"expert{index}@investor.sictic.ch"],
                adhoc_data={
                    "member_preferences": {"deep_dive_invitation": "standard"},
                },
            )
        )

    async def fake_dealum_import(startup):
        return SimpleNamespace(
            dataset_slug="example-startup",
            dealum_name=startup,
            dealum_url="https://dealum.example/app/1",
            application_path=None,
        )

    async def fake_startup_profile(*_args, **_kwargs):
        return []

    async def fake_expert_search(startup, *, exclude_experts, top_k):
        assert "interested-member" in exclude_experts
        assert top_k == 16
        rows = [
            "| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |",
            "|---|---|---|---|---|",
        ]
        for index in range(12):
            rows.append(
                f"| {index + 1} | Expert {index} | expert{index}@example.com | "
                f"expert-{index} | reason {index} |"
            )
        insight = InsightFile(startup, "expert_search", "manual")
        insight.save("\n".join(rows))
        return [insight]

    monkeypatch.setattr(module, "dealum_import", fake_dealum_import)
    monkeypatch.setattr(module, "startup_profile", fake_startup_profile)
    monkeypatch.setattr(module, "expert_search", fake_expert_search)
    monkeypatch.setattr(module, "member_preferences", lambda *_args: members)
    monkeypatch.setattr(module, "llm_model", lambda: "ollama/test_model:1b")

    [insight] = await deep_dive_invitation(
        "Example Startup",
        founders=[Person(full_name="Jane Founder", email_addresses=["jane@startup.ch"])],
        investors=[
            Person(
                full_name="Interested Member",
                email_addresses=["member@gmail.com"],
            ),
            Person(full_name="FONGIT"),
        ],
    )
    content = insight.content()
    email = content.split("# Email draft", 1)[1]

    assert content.startswith("# Review notices")
    assert "## Action required before sending" in content
    assert "## Informational" in content
    assert "Automatic extraction of interested investors from Dealum is not configured" in content
    assert "From:  \njoelle@sictic.ch" in email
    assert "To:  \nJane Founder <jane@startup.ch>" in email
    assert "Cc:  \nInterested Member <member@gmail.com>" in email
    assert "FONGIT | <insert email here>" in email
    assert "member@investor.sictic.ch" not in email
    assert "Bcc:  \nExpert 0 <expert0@investor.sictic.ch>,  \n" in email
    assert "Expert 9 <expert9@investor.sictic.ch>" in email
    body = email.split("Subject:", 1)[1]
    assert "Expert 0" not in body
    assert "reason 0" not in body
    assert "[Dealum application](https://dealum.example/app/1)" in email
    assert "Dear Founders, Investors and Industry Experts," in email
    assert "### Founders: Action Required" not in email
    assert "### Industry Experts: FYI" not in email
    assert "To:  \nJane Founder <jane@startup.ch>  \n\nCc:" in email
    assert "Member preference opt-outs excluded from expert search: 1" in content
    assert "Interested members excluded from expert search: 1" in content

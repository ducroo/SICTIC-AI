from lib.insights import InsightFile
from lib.people.discovery import persons_in_dataset
from lib.people.model import Person
from lib.storage import get_storage


def _manual_path(dataset: str) -> str:
    return InsightFile(
        dataset=dataset,
        skill="persons_in_dataset",
        model="manual",
    ).path


def test_persons_in_dataset_reads_manual_insight_table(mock_env):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")
    storage.write_text(
        manual_path,
        "\n".join(
            [
                "# Persons in sictic-members",
                "",
                "| full-name | linkedin-id | email-addresses |",
                "|---|---|---|",
                "| Urs Gubser | urs-gubser | urs@gubser.ch, urs.gubser@investor.sictic.ch |",
                "| Jane Doe | | jane@example.com |",
                "| | no-name | |",
                "| | |",
            ]
        )
        + "\n",
    )

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(
            full_name="Urs Gubser",
            linkedin_id="urs-gubser",
            email_addresses=["urs@gubser.ch", "urs.gubser@investor.sictic.ch"],
        ),
        Person(
            full_name="Jane Doe",
            linkedin_id="",
            email_addresses=["jane@example.com"],
        ),
        Person(full_name="", linkedin_id="no-name"),
    ]


def test_persons_in_dataset_reads_manual_insight_url_list(mock_env):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")
    storage.write_text(
        manual_path,
        "\n".join(
            [
                "# Persons in sictic-members",
                "",
                "https://www.linkedin.com/in/ursgubser/",
                "https://www.linkedin.com/in/jane-doe/?originalSubdomain=ch",
                "not a profile",
            ]
        )
        + "\n",
    )

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(full_name="", linkedin_id="ursgubser"),
        Person(full_name="", linkedin_id="jane-doe"),
    ]


def test_persons_in_dataset_ignores_linkedin_example_in_intro(mock_env):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")
    storage.write_text(
        manual_path,
        "\n".join(
            [
                "# Persons in sictic-members",
                "",
                "LinkedIn URL = [https://www.linkedin.com/in/linkedinID](https://www.linkedin.com/in/linkedinID)",
                "",
                "| full-name | linkedin-id | email-addresses |",
                "|---|---|---|",
                "| Urs Gubser | urs-gubser | urs@gubser.ch |",
            ]
        )
        + "\n",
    )

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(
            full_name="Urs Gubser",
            linkedin_id="urs-gubser",
            email_addresses=["urs@gubser.ch"],
        )
    ]


def test_persons_in_dataset_reads_legacy_manual_table_headers(mock_env, mocker):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")
    storage.write_text(
        manual_path,
        "\n".join(
            [
                "# Persons in sictic-members",
                "",
                "Deal leads, feel free to add or remove employees \\- SICTIC-AI will remember the edits.",
                "",
                "| full\\_name | linkedin_id |",
                "| :---- | :---- |",
                "| Patrick Schuler | schulerp |",
            ]
        )
        + "\n",
    )
    adapter_cls = mocker.patch("lib.people.discovery.LinkedInResolver")
    adapter_cls.return_value.get_cached_persons.return_value = [
        Person(full_name="Patrick Schuler", linkedin_id="schulerp", email_addresses=["patrick@example.com"])
    ]

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(
            full_name="Patrick Schuler",
            linkedin_id="schulerp",
        )
    ]


def test_persons_in_dataset_writes_discovered_people_to_manual_insight(mock_env, mocker):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")

    adapter_cls = mocker.patch("lib.people.discovery.LinkedInResolver")
    adapter_cls.return_value.get_cached_persons.return_value = [
        Person(full_name="Urs Gubser", linkedin_id="urs-gubser", email_addresses=["urs@gubser.ch"]),
        Person(full_name="", linkedin_id="jane-doe"),
    ]

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(full_name="Urs Gubser", linkedin_id="urs-gubser", email_addresses=["urs@gubser.ch"]),
        Person(full_name="", linkedin_id="jane-doe"),
    ]
    assert storage.exists(manual_path)
    assert storage.read_text(manual_path) == "\n".join(
        [
            "# Persons in sictic_members",
            "",
            "Deal leads, feel free to add or remove employees - SICTIC-AI will remember the edits; this file will never be overwritten.",
            "",
            "| full-name | linkedin-id | email-addresses |",
            "|---|---|---|",
            "| Urs Gubser | urs-gubser | urs@gubser.ch |",
            "|  | jane-doe |  |",
            "",
        ]
    )


def test_persons_in_dataset_rediscovers_when_manual_insight_is_empty(
    mock_env,
    mocker,
):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")
    storage.write_text(manual_path, "")

    adapter_cls = mocker.patch("lib.people.discovery.LinkedInResolver")
    adapter_cls.return_value.get_cached_persons.return_value = [
        Person(full_name="Urs Gubser", linkedin_id="urs-gubser")
    ]

    persons = persons_in_dataset("sictic_members")

    assert persons == [Person(full_name="Urs Gubser", linkedin_id="urs-gubser")]
    assert "| Urs Gubser | urs-gubser |  |" in storage.read_text(manual_path)

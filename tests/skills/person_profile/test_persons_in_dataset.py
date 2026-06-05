from lib.insight_filepath import get_insight_filepath
from lib.models.person import Person
from lib.storage import get_storage
from lib.storage_domains import persons_registry_path
from skills.person_profile.persons_in_dataset import persons_in_dataset


def _legacy_manual_path(dataset: str) -> str:
    return get_insight_filepath(
        dataset_name=dataset,
        skill_name="persons_in_dataset",
        model="manual",
        subdir=False,
    )


def _manual_path(dataset: str) -> str:
    return persons_registry_path(dataset)


def test_persons_in_dataset_reads_manual_registry_table(mock_env):
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
        Person(full_name="Jane Doe", linkedin_id="", email_addresses=["jane@example.com"]),
        Person(full_name="", linkedin_id="no-name"),
    ]


def test_persons_in_dataset_reads_manual_registry_url_list(mock_env):
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
    adapter_cls = mocker.patch("skills.person_profile.persons_in_dataset.LinkedInAdapter")
    adapter_cls.return_value.get_cached_persons.return_value = [
        Person(full_name="Patrick Schuler", linkedin_id="schulerp", email_addresses=["patrick@example.com"])
    ]

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(full_name="Patrick Schuler", linkedin_id="schulerp")
    ]


def test_persons_in_dataset_falls_back_to_legacy_manual_insight(mock_env):
    storage = get_storage()
    manual_path = _legacy_manual_path("sictic-members")
    storage.write_text(
        manual_path,
        "\n".join(
            [
                "# Persons in sictic-members",
                "",
                "| full_name | linkedinID |",
                "|---|---|",
                "| Urs Gubser | urs-gubser |",
            ]
        )
        + "\n",
    )

    persons = persons_in_dataset("sictic_members")

    assert persons == [Person(full_name="Urs Gubser", linkedin_id="urs-gubser")]


def test_persons_in_dataset_writes_discovered_people_to_manual_registry(mock_env, mocker):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")

    adapter_cls = mocker.patch("skills.person_profile.persons_in_dataset.LinkedInAdapter")
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

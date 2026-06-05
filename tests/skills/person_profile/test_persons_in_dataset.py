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
                "| full_name | linkedinID |",
                "|---|---|",
                "| Urs Gubser | urs-gubser |",
                "| Jane Doe | |",
                "| | no-name |",
                "| | |",
            ]
        )
        + "\n",
    )

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(full_name="Urs Gubser", linkedinID="urs-gubser"),
        Person(full_name="Jane Doe", linkedinID=""),
        Person(full_name="", linkedinID="no-name"),
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
        Person(full_name="", linkedinID="ursgubser"),
        Person(full_name="", linkedinID="jane-doe"),
    ]


def test_persons_in_dataset_reads_drive_exported_escaped_table(mock_env):
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
                "| full\\_name | linkedinID |",
                "| :---- | :---- |",
                "| Patrick Schuler | schulerp |",
            ]
        )
        + "\n",
    )

    persons = persons_in_dataset("sictic_members")

    assert persons == [Person(full_name="Patrick Schuler", linkedinID="schulerp")]


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

    assert persons == [Person(full_name="Urs Gubser", linkedinID="urs-gubser")]


def test_persons_in_dataset_writes_discovered_people_to_manual_registry(mock_env, mocker):
    storage = get_storage()
    manual_path = _manual_path("sictic-members")

    adapter_cls = mocker.patch("skills.person_profile.persons_in_dataset.LinkedInAdapter")
    adapter_cls.return_value.get_cached_persons.return_value = [
        Person(full_name="Urs Gubser", linkedinID="urs-gubser"),
        Person(full_name="", linkedinID="jane-doe"),
    ]

    persons = persons_in_dataset("sictic_members")

    assert persons == [
        Person(full_name="Urs Gubser", linkedinID="urs-gubser"),
        Person(full_name="", linkedinID="jane-doe"),
    ]
    assert storage.exists(manual_path)
    assert storage.read_text(manual_path) == "\n".join(
        [
            "# Persons in sictic_members",
            "",
            "Deal leads, feel free to add or remove employees - SICTIC-AI will remember the edits; this file will never be overwritten. BTW linkedinURL = https://www.linkedin.com/in/linkedinID",
            "",
            "| full_name | linkedinID |",
            "|---|---|",
            "| Urs Gubser | urs-gubser |",
            "|  | jane-doe |",
            "",
        ]
    )

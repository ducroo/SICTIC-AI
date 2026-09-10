from lib.people import Person
import importlib


def test_member_preferences_stub_returns_full_roster_with_standard_default(monkeypatch):
    module = importlib.import_module("skills.member_preferences.member_preferences")

    people = [
        Person(full_name="One"),
        Person(
            full_name="Two",
            adhoc_data={
                "member_preferences": {"deep_dive_invitation": "none"},
            },
        ),
    ]
    monkeypatch.setattr(module, "persons_in_dataset", lambda _dataset: people)

    assert "member_preferences" not in people[0].adhoc_data

    result = module.member_preferences()

    assert result == people
    assert [
        person.adhoc_data["member_preferences"]["deep_dive_invitation"]
        for person in result
    ] == ["standard", "none"]

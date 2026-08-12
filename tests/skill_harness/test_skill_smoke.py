from __future__ import annotations

import pytest

from lib.insights import InsightFile
from lib.people.model import Person
from lib.storage import get_storage
from skills.harness.harness import dispatch_command
from tests.skill_harness.cases import HARNESS_SMOKE_COMMANDS


def assert_insight_result(result):
    assert isinstance(result, list)
    assert all(isinstance(insight, InsightFile) for insight in result)


@pytest.mark.asyncio
async def test_startup_profile_uses_local_fixture_storage(mocked_skill_boundaries):
    from skills.startup_profile.startup_profile import startup_profile

    result = await startup_profile("example-startup")
    assert_insight_result(result)
    [insight] = result
    content = insight.content()
    path = insight.path

    assert "Fixture answer" in content
    assert path.startswith("storage/startups/example-startup/insights/")
    assert get_storage().exists(path)


@pytest.mark.asyncio
async def test_startup_traction_uses_local_fixture_storage(mocked_skill_boundaries):
    from skills.startup_traction.startup_traction import startup_traction

    result = await startup_traction("example-startup")
    assert_insight_result(result)
    [insight] = result
    content = insight.content()

    assert "Fixture answer" in content
    assert InsightFile("example-startup", "startup_traction", "ollama/test_model:1b").exists()


@pytest.mark.asyncio
async def test_person_profile_uses_fixture_people_and_linkedin(mocked_skill_boundaries):
    from skills.person_profile.person_profile import person_profile_as_person_objects

    people = await person_profile_as_person_objects("sictic-members", "Jane Doe")

    assert len(people) == 1
    assert people[0].full_name == "Jane Doe"
    assert "Full-name: Jane Doe" in people[0].person_profile_markdown


@pytest.mark.asyncio
async def test_team_profile_uses_mocked_person_context(mocked_skill_boundaries):
    from skills.team_profile.team_profile import team_profile

    [insight] = await team_profile("example-startup")
    content = insight.content()
    path = insight.path

    assert "Fixture LLM profile" in content
    assert path.startswith("storage/startups/example-startup/insights/")
    assert get_storage().exists(path)


@pytest.mark.asyncio
async def test_investor_profile_composes_from_local_insights(mocked_skill_boundaries):
    from skills.investor_profile.investor_profile import investor_profile

    result = await investor_profile("sictic-members")

    assert_insight_result(result)
    assert len(result) == 1
    assert InsightFile(
        "sictic-members",
        "investor_profile",
        "ollama/test_model:1b",
        identifier="jane-doe",
        subdir=True,
    ).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "function_name", "args", "expected"),
    [
        (
            "skills.expert_search.expert_search",
            "expert_search",
            ("example-startup",),
            "Jane Doe",
        ),
        (
            "skills.potential_investors.potential_investors",
            "potential_investors",
            ("example-startup",),
            "Jane Doe",
        ),
        (
            "skills.advocates.advocates",
            "advocates",
            ("fixture-event", "Fixture event"),
            "Jane Doe",
        ),
        (
            "skills.suggested_startups.suggested_startups",
            "suggested_startups",
            ("sictic-members", ["example-startup"], ["Jane Doe"], 1),
            "Fixture rationale",
        ),
    ],
)
async def test_ranking_style_skills_smoke(
    mocked_skill_boundaries,
    module_name,
    function_name,
    args,
    expected,
):
    module = __import__(module_name, fromlist=[function_name])

    result = await getattr(module, function_name)(*args)

    assert_insight_result(result)
    assert len(result) == 1
    assert expected in result[0].content()


@pytest.mark.asyncio
async def test_suggested_startups_does_not_save_invalid_response(
    mocked_skill_boundaries,
    monkeypatch,
    caplog,
):
    import skills.suggested_startups.suggested_startups as module

    async def invalid_response(*_args, **_kwargs):
        raise ValueError("response does not match the schema")

    monkeypatch.setattr(module, "generate_report", invalid_response)

    result = await module.suggested_startups(
        "sictic-members",
        ["example-startup"],
        ["Jane Doe"],
        1,
    )

    assert result == []
    assert "Failed to generate suggested startups for Jane Doe" in caplog.text
    assert "0 cached, 0 generated, 1 failed" in caplog.text
    assert not InsightFile(
        "sictic-members",
        "suggested_startups",
        "ollama/test_model:1b",
        identifier="Jane Doe",
        subdir=True,
    ).exists()


@pytest.mark.asyncio
async def test_suggested_startups_continues_after_investor_failure(
    mocked_skill_boundaries,
    monkeypatch,
    caplog,
):
    import skills.suggested_startups.inputs as inputs
    import skills.suggested_startups.suggested_startups as module

    people = [
        Person(full_name="Jane Doe", linkedin_id="jane-doe"),
        Person(full_name="John Roe", linkedin_id="john-roe"),
    ]
    monkeypatch.setattr(inputs, "persons_in_dataset", lambda _dataset: people)
    monkeypatch.setattr(
        module,
        "load_investor_profiles",
        lambda *_args, **_kwargs: {
            "jane-doe": "Jane profile",
            "john-roe": "John profile",
        },
    )

    async def generate_report(investor, *_args, **_kwargs):
        if investor == "Jane Doe":
            raise ValueError("duplicate startup")
        return "# Startup Suggestions for John Roe\n\nValid report."

    monkeypatch.setattr(module, "generate_report", generate_report)

    result = await module.suggested_startups(
        "sictic-members",
        ["example-startup"],
        ["Jane Doe", "John Roe"],
        1,
    )

    assert len(result) == 1
    assert result[0].identifier == "John Roe"
    assert "Valid report" in result[0].content()
    assert "Failed to generate suggested startups for Jane Doe" in caplog.text
    assert "0 cached, 1 generated, 1 failed" in caplog.text


@pytest.mark.asyncio
async def test_dd_checks_writes_report_from_local_fixture(mocked_skill_boundaries):
    from skills.dd_checks.dd_checks import dd_checks

    result = await dd_checks("example-startup")
    assert_insight_result(result)
    [insight] = result
    path = insight.path

    assert path.startswith("storage/startups/example-startup/insights/")
    report = get_storage().read_text(path)
    assert "Due Diligence" in report
    assert "| No | Check | Status | Rationale | Source documents |" in report
    json_insights = get_storage().list(
        "storage/startups/example-startup/insights/batch-audit",
        suffix=".json",
    )
    assert any(name.startswith("dd-checks-") for name in json_insights)


@pytest.mark.asyncio
async def test_batch_audit_writes_checklist_insight(mocked_skill_boundaries):
    from skills.batch_audit.batch_audit import batch_audit

    result = await batch_audit(
        "example-startup",
        """# Commercial

## Traction

### Customer traction

Is there evidence of customer traction?
""",
    )
    assert_insight_result(result)
    [insight] = result

    assert insight.exists()
    assert InsightFile(
        "example-startup",
        "batch_audit",
        "ollama/test_model:1b",
        identifier="batch_audit-Commercial",
        subdir=True,
        extension="json",
    ).exists()


@pytest.mark.asyncio
async def test_submission_ready_writes_report_from_local_fixture(
    mocked_skill_boundaries,
):
    from skills.submission_ready.submission_ready import submission_ready

    result = await submission_ready("example-startup")

    assert_insight_result(result)
    assert len(result) == 2
    assert [insight.identifier for insight in result] == ["checklist", "response"]
    root = (
        "storage/startups/example-startup/insights/submission-ready"
    )
    run_id = get_storage().list(root)[0]
    files = get_storage().list(f"{root}/{run_id}")
    assert "checklist-test-model-1b.md" in files
    assert "response-test-model-1b.md" in files
    checklist = get_storage().read_text(
        f"{root}/{run_id}/checklist-test-model-1b.md"
    )
    assert "Completeness and Eligibility" in checklist
    assert "| Pass | Fixture evidence |" in checklist


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", sorted(HARNESS_SMOKE_COMMANDS))
async def test_harness_core_command_smoke(command_name, mocked_skill_boundaries, tmp_path):
    checklist = tmp_path / "checklist.md"
    checklist.write_text(
        "# Commercial\n\n## Traction\n\n### Customer traction\n\n"
        "Is there evidence of customer traction?\n",
        encoding="utf-8",
    )
    command = HARNESS_SMOKE_COMMANDS[command_name].format(checklist=checklist)

    result = await dispatch_command(command)

    assert result
    assert "Traceback" not in result

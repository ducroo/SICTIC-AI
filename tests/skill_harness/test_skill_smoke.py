from __future__ import annotations

import pytest

from lib.insights import InsightFile
from lib.storage import get_storage
from skills.harness.harness import dispatch_command
from tests.skill_harness.cases import HARNESS_SMOKE_COMMANDS


@pytest.mark.asyncio
async def test_startup_profile_uses_local_fixture_storage(mocked_skill_boundaries):
    from skills.startup_profile.startup_profile import startup_profile

    content, path = await startup_profile("example-startup")

    assert "Fixture answer" in content
    assert path.startswith("storage/startups/example-startup/insights/")
    assert get_storage().exists(path)


@pytest.mark.asyncio
async def test_startup_traction_uses_local_fixture_storage(mocked_skill_boundaries):
    from skills.startup_traction.startup_traction import startup_traction

    content = await startup_traction("example-startup")

    assert "Fixture answer" in content
    assert InsightFile("example-startup", "startup_traction", "ollama/test_model:1b").exists()


@pytest.mark.asyncio
async def test_person_profile_uses_fixture_people_and_linkedin(mocked_skill_boundaries):
    from skills.person_profile.person_profile import person_profile

    people = await person_profile("sictic-members", "Jane Doe")

    assert len(people) == 1
    assert people[0].full_name == "Jane Doe"
    assert "Full-name: Jane Doe" in people[0].person_profile


@pytest.mark.asyncio
async def test_team_profile_uses_mocked_person_context(mocked_skill_boundaries):
    from skills.team_profile.team_profile import team_profile

    content, path = await team_profile("example-startup")

    assert "Fixture LLM profile" in content
    assert path.startswith("storage/startups/example-startup/insights/")
    assert get_storage().exists(path)


@pytest.mark.asyncio
async def test_investor_profile_composes_from_local_insights(mocked_skill_boundaries):
    from skills.investor_profile.investor_profile import investor_profile

    result = await investor_profile("sictic-members")

    assert result.person_profiles == 1
    assert result.written == 1
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
            "Processed Jane Doe",
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

    assert expected in result


@pytest.mark.asyncio
async def test_dd_checks_writes_report_from_local_fixture(mocked_skill_boundaries):
    from skills.dd_checks.dd_checks import dd_checks

    path = await dd_checks("example-startup")

    assert path.startswith("storage/startups/example-startup/insights/")
    assert "Due Diligence" in get_storage().read_text(path)


@pytest.mark.asyncio
async def test_batch_audit_writes_checklist_insight(mocked_skill_boundaries):
    from skills.batch_audit.batch_audit import batch_audit

    result = await batch_audit("example-startup", "# Commercial\n- Is there traction?")

    assert "| 1.1 | Is there traction?" in result
    assert InsightFile(
        "example-startup",
        "batch_audit",
        "ollama/test_model:1b",
        identifier="Commercial",
        subdir=True,
    ).exists()


@pytest.mark.asyncio
async def test_submission_ready_writes_report_from_local_fixture(
    mocked_skill_boundaries,
):
    from skills.submission_ready.submission_ready import submission_ready

    result = await submission_ready("example-startup")

    assert "Proposed action:" in result
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
    checklist.write_text("# Commercial\n- Is there traction?\n", encoding="utf-8")
    command = HARNESS_SMOKE_COMMANDS[command_name].format(checklist=checklist)

    result = await dispatch_command(command)

    assert result
    assert "Traceback" not in result

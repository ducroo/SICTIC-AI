from typer.testing import CliRunner


class FakeInsight:
    def __init__(self, path: str, content: str):
        self.path = path
        self._content = content

    def content(self):
        return self._content


def test_batch_audit_cli_forwards_calling_skill(mocker, tmp_path):
    from skills.batch_audit.__main__ import app

    checklist = tmp_path / "corporation.md"
    checklist.write_text("# 2 Corporation-General\n", encoding="utf-8")

    result_insight = FakeInsight(
        (
            "storage/startups/avientus/insights/batch-audit/"
            "dd-checks-2-corporation-general-gemma4.json"
        ),
        "{}",
    )

    async def fake_batch_audit(dataset, markdown, *, skill_name):
        assert dataset == "avientus"
        assert markdown == "# 2 Corporation-General\n"
        assert skill_name == "dd_checks"
        return [result_insight]

    mocker.patch(
        "skills.batch_audit.__main__.batch_audit",
        side_effect=fake_batch_audit,
    )
    result = CliRunner().invoke(
        app,
        ["avientus", str(checklist), "--skill-name", "dd_checks"],
    )

    assert result.exit_code == 0
    assert "batch-audit/dd-checks-" in result.output


def test_llm_chat_cli_awaits_async_function(mocker):
    from skills.llm_chat.__main__ import app

    async def fake_llm_chat(prompt):
        return "mocked response"

    mocker.patch("skills.llm_chat.__main__.llm_chat", side_effect=fake_llm_chat)
    result = CliRunner().invoke(app, ["hello"])

    assert result.exit_code == 0
    assert "mocked response" in result.output
    assert "coroutine object" not in result.output


def test_startup_traction_cli_awaits_async_function(mocker):
    from skills.startup_traction.__main__ import app

    async def fake_startup_traction(startup):
        return [FakeInsight(f"insights/{startup}/traction.md", f"traction for {startup}")]

    mocker.patch("skills.startup_traction.__main__.startup_traction", side_effect=fake_startup_traction)
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "traction for avientus" in result.output
    assert "coroutine object" not in result.output


def test_dd_checks_cli_awaits_async_function(mocker):
    from skills.dd_checks.__main__ import app

    async def fake_dd_checks(startup):
        return [FakeInsight(f"insights/{startup}/dd.md", "DD checks complete")]

    mocker.patch("skills.dd_checks.__main__.dd_checks", side_effect=fake_dd_checks)
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "DD checks complete" in result.output
    assert "insights/avientus/dd.md" in result.output
    assert "coroutine object" not in result.output


def test_dd_priorities_cli_awaits_async_function(mocker):
    from skills.dd_priorities.__main__ import app

    async def fake_dd_priorities(startup):
        return [
            FakeInsight(
                f"insights/{startup}/dd-priorities.md",
                "DD priorities complete",
            )
        ]

    mocker.patch(
        "skills.dd_priorities.__main__.dd_priorities",
        side_effect=fake_dd_priorities,
    )
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "DD priorities complete" in result.output
    assert "insights/avientus/dd-priorities.md" in result.output
    assert "coroutine object" not in result.output


def test_submission_ready_cli_awaits_async_function(mocker):
    from skills.submission_ready.__main__ import app

    async def fake_submission_ready(startups):
        return [
            FakeInsight(
                f"insights/{startups[0]}/submission-ready.md",
                "Submission ready",
            )
        ]

    mocker.patch(
        "skills.submission_ready.__main__.submission_ready",
        side_effect=fake_submission_ready,
    )
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "insights/avientus/submission-ready.md" in result.output
    assert "coroutine object" not in result.output

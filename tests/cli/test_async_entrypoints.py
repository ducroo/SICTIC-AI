from typer.testing import CliRunner


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
        return f"traction for {startup}"

    mocker.patch("skills.startup_traction.__main__.startup_traction", side_effect=fake_startup_traction)
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "traction for avientus" in result.output
    assert "coroutine object" not in result.output


def test_dd_checks_cli_awaits_async_function(mocker):
    from skills.dd_checks.__main__ import app

    async def fake_dd_checks(startup):
        return f"insights/{startup}/dd.md"

    mocker.patch("skills.dd_checks.__main__.dd_checks", side_effect=fake_dd_checks)
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "DD checks complete" in result.output
    assert "insights/avientus/dd.md" in result.output
    assert "coroutine object" not in result.output


def test_submission_ready_cli_awaits_async_function(mocker):
    from skills.submission_ready.__main__ import app

    async def fake_submission_ready(startup):
        return f"insights/{startup}/submission-ready.md"

    mocker.patch(
        "skills.submission_ready.__main__.submission_ready",
        side_effect=fake_submission_ready,
    )
    result = CliRunner().invoke(app, ["--startup", "avientus"])

    assert result.exit_code == 0
    assert "Submission readiness check complete" in result.output
    assert "insights/avientus/submission-ready.md" in result.output
    assert "coroutine object" not in result.output

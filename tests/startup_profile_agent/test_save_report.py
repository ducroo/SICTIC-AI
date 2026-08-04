from typer.testing import CliRunner

from skills.startup_profile_agent.__main__ import app


class FakeInsightFile:
    def __init__(self, **kwargs):
        FakeInsightFile.last_kwargs = kwargs
        self.path = (
            "storage/startups/avientus/insights/"
            "startup-profile-avientus-claude-code-agent.md"
        )

    def save(self, content):
        FakeInsightFile.last_saved_content = content


def test_save_report_builds_insight_file_and_saves_content(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("# Startup Profile\n\nOneliner...", encoding="utf-8")

    mocker.patch(
        "skills.startup_profile_agent.startup_profile_agent.InsightFile",
        FakeInsightFile,
    )

    result = CliRunner().invoke(
        app,
        ["avientus", "--content-file", str(content_file)],
    )

    assert result.exit_code == 0
    assert FakeInsightFile.last_kwargs == {
        "dataset": "avientus",
        "skill": "startup_profile",
        "model": "anthropic/claude-code-agent",
        "prompt_key": "startup_profile_agent-v1",
    }
    assert FakeInsightFile.last_saved_content == "# Startup Profile\n\nOneliner..."
    assert result.output.strip() == (
        "storage/startups/avientus/insights/"
        "startup-profile-avientus-claude-code-agent.md"
    )


def test_save_report_accepts_custom_prompt_key(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("content", encoding="utf-8")

    mocker.patch(
        "skills.startup_profile_agent.startup_profile_agent.InsightFile",
        FakeInsightFile,
    )

    result = CliRunner().invoke(
        app,
        ["daav", "--content-file", str(content_file), "--prompt-key", "custom-v2"],
    )

    assert result.exit_code == 0
    assert FakeInsightFile.last_kwargs["prompt_key"] == "custom-v2"


def test_save_report_cli_reports_errors_and_exits_nonzero(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("content", encoding="utf-8")

    class ExplodingInsightFile:
        def __init__(self, **kwargs):
            pass

        def save(self, content):
            raise RuntimeError("disk full")

    mocker.patch(
        "skills.startup_profile_agent.startup_profile_agent.InsightFile",
        ExplodingInsightFile,
    )

    result = CliRunner().invoke(
        app, ["avientus", "--content-file", str(content_file)]
    )

    assert result.exit_code == 1
    assert "disk full" in result.output

from typer.testing import CliRunner

from skills.startup_profile_agent.save_report import app


def test_save_report_builds_insight_file_and_saves_content(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("# Startup Profile\n\nOneliner...", encoding="utf-8")

    insight_file_cls = mocker.patch(
        "skills.startup_profile_agent.save_report.InsightFile"
    )
    insight_instance = insight_file_cls.return_value
    insight_instance.path = (
        "storage/startups/avientus/insights/"
        "startup-profile-avientus-claude-code-agent.md"
    )

    result = CliRunner().invoke(
        app,
        ["avientus", "--content-file", str(content_file)],
    )

    assert result.exit_code == 0
    insight_file_cls.assert_called_once_with(
        dataset="avientus",
        skill="startup_profile",
        model="anthropic/claude-code-agent",
        prompt_key="startup_profile_agent-v1",
    )
    insight_instance.save.assert_called_once_with(
        "# Startup Profile\n\nOneliner..."
    )
    assert insight_instance.path in result.output


def test_save_report_accepts_custom_prompt_key(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("content", encoding="utf-8")

    insight_file_cls = mocker.patch(
        "skills.startup_profile_agent.save_report.InsightFile"
    )
    insight_file_cls.return_value.path = "some/path.md"

    result = CliRunner().invoke(
        app,
        ["daav", "--content-file", str(content_file), "--prompt-key", "custom-v2"],
    )

    assert result.exit_code == 0
    insight_file_cls.assert_called_once_with(
        dataset="daav",
        skill="startup_profile",
        model="anthropic/claude-code-agent",
        prompt_key="custom-v2",
    )

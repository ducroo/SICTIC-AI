from typer.testing import CliRunner

from skills.dd_checks_agent.save_report import app


class FakeInsightFile:
    def __init__(self, **kwargs):
        FakeInsightFile.last_kwargs = kwargs
        self.path = (
            "storage/startups/avientus/insights/"
            "dd-checks-avientus-claude-code-agent.md"
        )

    def save(self, content):
        FakeInsightFile.last_saved_content = content


def test_save_report_cli_builds_insight_file_with_defaults(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("# M&A Due Diligence Checks\n\nbody", encoding="utf-8")

    mocker.patch("skills.dd_checks_agent.save_report.InsightFile", FakeInsightFile)

    result = CliRunner().invoke(
        app, ["avientus", "--content-file", str(content_file)]
    )

    assert result.exit_code == 0
    assert FakeInsightFile.last_kwargs == {
        "dataset": "avientus",
        "skill": "dd_checks",
        "model": "anthropic/claude-code-agent",
        "prompt_key": "dd_checks_agent-v1",
    }
    assert FakeInsightFile.last_saved_content == "# M&A Due Diligence Checks\n\nbody"
    assert result.output.strip() == (
        "storage/startups/avientus/insights/"
        "dd-checks-avientus-claude-code-agent.md"
    )


def test_save_report_cli_accepts_custom_prompt_key(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("content", encoding="utf-8")

    mocker.patch("skills.dd_checks_agent.save_report.InsightFile", FakeInsightFile)

    result = CliRunner().invoke(
        app,
        [
            "avientus",
            "--content-file",
            str(content_file),
            "--prompt-key",
            "custom-key",
        ],
    )

    assert result.exit_code == 0
    assert FakeInsightFile.last_kwargs["prompt_key"] == "custom-key"


def test_save_report_cli_reports_errors_and_exits_nonzero(tmp_path, mocker):
    content_file = tmp_path / "report.md"
    content_file.write_text("content", encoding="utf-8")

    class ExplodingInsightFile:
        def __init__(self, **kwargs):
            pass

        def save(self, content):
            raise RuntimeError("disk full")

    mocker.patch(
        "skills.dd_checks_agent.save_report.InsightFile", ExplodingInsightFile
    )

    result = CliRunner().invoke(
        app, ["avientus", "--content-file", str(content_file)]
    )

    assert result.exit_code == 1
    assert "disk full" in result.output

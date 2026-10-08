from pathlib import Path

from bs4 import BeautifulSoup
import pytest
from typer.testing import CliRunner

from skills.send_gmail.__main__ import app
from skills.send_gmail.render_email import convert_file, markdown_to_email


def test_email_preserves_content_links_code_and_table_alignment():
    html = markdown_to_email(
        "# Zürich & team\n\n**Ready** for [review](https://example.com/?a=1&b=2).\n\n"
        "- First\n- Second\n\n| Name | Amount |\n| --- | ---: |\n| André | 100 |\n\n"
        "```python\nprint('<hello>')\n```\n"
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.h1.get_text() == "Zürich & team"
    assert soup.strong.get_text() == "Ready"
    assert soup.a["href"] == "https://example.com/?a=1&b=2"
    assert [li.get_text() for li in soup.select("li")] == ["First", "Second"]
    assert soup.pre.get_text().strip() == "print('<hello>')"
    assert soup.select("td")[0].get_text() == "André"
    assert soup.select("td")[1]["style"].endswith("text-align:right") or soup.select("td")[1]["style"].endswith("text-align:right;")
    assert "padding:" in soup.th["style"]
    assert "background-color:" in soup.th["style"]
    assert soup.select("style, script") == []


def test_raw_html_is_text_and_unsafe_links_are_not_active():
    soup = BeautifulSoup(markdown_to_email(
        '<script>alert(1)</script>\n\n[click](javascript:alert(1))\n\n<img src=x onerror=alert(1)>'
    ), "html.parser")
    assert not soup.select("script, img, a")
    assert "<script>alert(1)</script>" in soup.get_text()


def test_cli_writes_complete_utf8_output(tmp_path):
    source = tmp_path / "insight with spaces.md"
    source.write_text("# Grüezi\n\nThe complete insight.", encoding="utf-8")
    output = tmp_path / "email.html"
    result = CliRunner().invoke(app, [str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(output)
    assert "The complete insight." in output.read_text(encoding="utf-8")
    assert "Grüezi" in output.read_text(encoding="utf-8")


def test_temporary_outputs_are_private_unique_and_source_is_preserved(tmp_path):
    source = tmp_path / "insight.md"
    source.write_text("Original", encoding="utf-8")
    paths = []
    try:
        paths = [convert_file(source), convert_file(source)]
        assert paths[0] != paths[1]
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in paths)
        with pytest.raises(ValueError, match="must differ"):
            convert_file(source, source)
        assert source.read_text(encoding="utf-8") == "Original"
    finally:
        for path in paths:
            path.unlink()


def test_missing_input_fails_without_creating_output(tmp_path):
    output = tmp_path / "email.html"
    result = CliRunner().invoke(app, [str(tmp_path / "missing.md"), "--output", str(output)])
    assert result.exit_code != 0
    assert not output.exists()

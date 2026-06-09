from types import SimpleNamespace

from typer.testing import CliRunner
from lib.dealum_import import DealumApplicationNotFoundError


def _result(name: str, *, found: bool = True):
    slug = name.lower().replace(" ", "-")
    return SimpleNamespace(
        application_found=found,
        dataset_slug=slug,
        changed=True,
        downloaded_files=2,
        skipped_files=0,
        step="Jury",
        dealum_url=f"https://app.dealum.com/#/dealroom/19180?application={slug}",
        application_path=f"storage/startups/{slug}/datasets/dealum/application.md",
        manifest_path=f"storage/startups/{slug}/datasets/dealum/manifest.json",
    )


def test_dealum_import_cli_imports_comma_separated_startups(mocker):
    from skills.dealum_import.__main__ import app

    imported = []

    async def fake_dealum_import(name):
        imported.append(name)
        return _result(name)

    mocker.patch(
        "skills.dealum_import.__main__.dealum_import",
        side_effect=fake_dealum_import,
    )

    result = CliRunner().invoke(app, ["Avientus, daav, prevision medicine"])

    assert result.exit_code == 0
    assert imported == ["Avientus", "daav", "prevision medicine"]
    assert "Imported avientus" in result.output
    assert "Imported daav" in result.output
    assert "Imported prevision-medicine" in result.output
    assert "DEALUM_URL: https://app.dealum.com/#/dealroom/19180?application=avientus" in result.output


def test_dealum_import_cli_continues_after_missing_application(mocker):
    from skills.dealum_import.__main__ import app

    imported = []

    async def fake_dealum_import(name):
        imported.append(name)
        return _result(name, found=name != "missing")

    mocker.patch(
        "skills.dealum_import.__main__.dealum_import",
        side_effect=fake_dealum_import,
    )

    result = CliRunner().invoke(app, ["Avientus, missing, daav"])

    assert result.exit_code == 1
    assert imported == ["Avientus", "missing", "daav"]
    assert "No Dealum application found for missing." in result.output
    assert "Imported daav" in result.output


def test_dealum_import_cli_reports_reconciliation_failure_and_continues(mocker):
    from skills.dealum_import.__main__ import app

    imported = []

    async def fake_dealum_import(name):
        imported.append(name)
        if name == "novov":
            raise DealumApplicationNotFoundError(
                "No exact Dealum application match for 'novov'."
            )
        return _result(name)

    mocker.patch(
        "skills.dealum_import.__main__.dealum_import",
        side_effect=fake_dealum_import,
    )

    result = CliRunner().invoke(app, ["Avientus, novov, daav"])

    assert result.exit_code == 1
    assert imported == ["Avientus", "novov", "daav"]
    assert "Could not reconcile novov" in result.output
    assert "Imported daav" in result.output

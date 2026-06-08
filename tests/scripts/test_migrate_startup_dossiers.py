from pathlib import Path

from scripts.migrate_startup_dossiers import apply_plan, build_plan


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_migration_routes_files_and_directories_in_both_trees(mock_env, tmp_path):
    mirror = tmp_path / "mirror"
    for prefix, suffix in (
        ("storage/startups", ""),
        ("storage/datasets2md/startups", ".md"),
    ):
        datasets = mirror / prefix / "example" / "datasets"
        _write(datasets / f"loose.pdf{suffix}", "loose")
        _write(datasets / "Existing Folder" / f"nested.pdf{suffix}", "nested")
        _write(datasets / "linkedin" / f"person.json{suffix}", "linkedin")
        _write(datasets / "dealum" / f"application.md{suffix}", "dealum")

    plan = build_plan(mirror)

    assert not plan["conflicts"]
    apply_plan(plan)

    for prefix, suffix in (
        ("storage/startups", ""),
        ("storage/datasets2md/startups", ".md"),
    ):
        datasets = mirror / prefix / "example" / "datasets"
        assert (datasets / "snippets" / f"loose.pdf{suffix}").exists()
        assert (
            datasets / "data-room" / "Existing Folder" / f"nested.pdf{suffix}"
        ).exists()
        assert (datasets / "linkedin" / f"person.json{suffix}").exists()
        assert (datasets / "dealum" / f"application.md{suffix}").exists()
        assert (datasets / "post-deal").is_dir()

    assert (
        mirror
        / "storage/startups/example/datasets/__active_dataset__.md"
    ).exists()


def test_migration_merges_only_configured_aliases(mock_env, tmp_path):
    mirror = tmp_path / "mirror"
    _write(
        mirror / "storage/startups/expertvision/datasets/linkedin/person.json",
        "linkedin",
    )
    _write(
        mirror / "storage/startups/expertvision-ai/datasets/dealum/application.md",
        "dealum",
    )

    plan = build_plan(mirror)

    assert not plan["conflicts"]
    apply_plan(plan)
    assert (
        mirror
        / "storage/startups/expertvision/datasets/linkedin/person.json"
    ).exists()
    assert (
        mirror
        / "storage/startups/expertvision/datasets/dealum/application.md"
    ).exists()
    assert not (mirror / "storage/startups/expertvision-ai").exists()


def test_migration_reports_conflicting_destinations(mock_env, tmp_path):
    mirror = tmp_path / "mirror"
    _write(
        mirror / "storage/startups/expertvision/datasets/dealum/application.md",
        "old",
    )
    _write(
        mirror / "storage/startups/expertvision-ai/datasets/dealum/application.md",
        "new",
    )

    plan = build_plan(mirror)

    assert len(plan["conflicts"]) == 1

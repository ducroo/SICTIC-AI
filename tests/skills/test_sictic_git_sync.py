from pathlib import Path

from skills.sictic_git_sync.sictic_git_sync import _reconcile_workspace_copies


def test_reconcile_workspace_copies_repo_skills_without_symlinks(tmp_path):
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    repo_skill = repo / "skills" / "sample"
    repo_skill.mkdir(parents=True)
    (repo_skill / "SKILL.md").write_text("sample\n", encoding="utf-8")
    (repo_skill / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")

    logs = _reconcile_workspace_copies(repo, workspace)

    assert "Copied repo skill into workspace: sample" in logs
    assert (workspace / "sample" / "SKILL.md").read_text(encoding="utf-8") == "sample\n"
    assert not (workspace / "sample").is_symlink()
    assert not (workspace / "sample" / "SKILL.md").is_symlink()


def test_reconcile_workspace_replaces_old_symlink_install(tmp_path):
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    repo_skill = repo / "skills" / "sample"
    repo_skill.mkdir(parents=True)
    workspace.mkdir()
    (repo_skill / "SKILL.md").write_text("fresh\n", encoding="utf-8")
    (workspace / "sample").symlink_to(repo_skill, target_is_directory=True)

    _reconcile_workspace_copies(repo, workspace)

    assert (workspace / "sample").is_dir()
    assert not (workspace / "sample").is_symlink()
    assert (workspace / "sample" / "SKILL.md").read_text(encoding="utf-8") == "fresh\n"

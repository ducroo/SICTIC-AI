import os
import subprocess
from pathlib import Path


def test_install_script_copies_skills_and_sets_env(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    target = tmp_path / "workspace" / "skills"
    fake_site_packages = tmp_path / "site-packages"
    fake_site_packages.mkdir()

    skill_dir = source / "skills" / "example_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: example_skill\n---\n", encoding="utf-8")
    (skill_dir / "__main__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (skill_dir / "__pycache__").mkdir()
    (skill_dir / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")
    (source / "environment.yml").write_text(
        "name: sictic-test\n"
        "dependencies:\n"
        "  - python=3.12\n",
        encoding="utf-8",
    )
    (source / ".env-template").write_text(
        "REPO_PATH=\n"
        "WORKSPACE_PATH=\n"
        "LOCAL_STORAGE_PATH=\n"
        "LOCAL_DATA_PATH=\n"
        "CLOUD_PROVIDER=google\n"
        "CLOUD_STORAGE_PATH=\n",
        encoding="utf-8",
    )
    (source / ".env").write_text(
        "REPO_PATH=\n"
        "WORKSPACE_PATH=\n"
        "LOCAL_STORAGE_PATH=\n"
        "LOCAL_DATA_PATH=\n"
        "CLOUD_PROVIDER=google\n"
        "CLOUD_STORAGE_PATH=\n"
        "STORAGE_PROVIDER=google\n"
        "DEFAULT_LLM=legacy\n"
        "OLLAMA_NUM_CTX=4096\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python-fake"
    fake_python.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"pip\" ]; then exit 0; fi\n"
        "if [ \"$1\" = \"-c\" ]; then printf '%s\\n' \"$FAKE_SITE_PACKAGES\"; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_conda = fake_bin / "conda"
    fake_conda.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"run\" ]; then printf '%s\\n' \"$FAKE_PYTHON\"; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_conda.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_PYTHON"] = str(fake_python)
    env["FAKE_SITE_PACKAGES"] = str(fake_site_packages)

    result = subprocess.run(
        [
            str(repo_root / "install.sh"),
            "--source",
            str(source),
            "--target",
            str(target),
            "--skip-env",
            "--non-interactive",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert (target / "example_skill" / "SKILL.md").is_file()
    assert (target / "example_skill" / "__main__.py").is_file()
    assert not (target / "example_skill" / "SKILL.md").is_symlink()
    assert not (target / "example_skill" / "__pycache__").exists()
    assert (fake_site_packages / "sictic-ai-repo.pth").read_text(encoding="utf-8").strip() == str(source)

    env_file = (source / ".env").read_text(encoding="utf-8")
    assert f"REPO_PATH={source}" in env_file
    assert f"WORKSPACE_PATH={target}" in env_file
    assert f"LOCAL_STORAGE_PATH={source / '.storage'}" in env_file
    assert f"LOCAL_DATA_PATH={source}" in env_file
    assert "STORAGE_PROVIDER=" not in env_file
    assert "DEFAULT_LLM=" not in env_file
    assert "OLLAMA_NUM_CTX=" not in env_file

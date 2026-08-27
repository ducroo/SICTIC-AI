import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_rclone(tmp_path: Path) -> Path:
    fake = tmp_path / "rclone"
    fake.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"bisync\" ] && [ \"$2\" = \"--help\" ]; then\n"
        "  echo --recover\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"listremotes\" ]; then\n"
        "  echo gdrive:\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"config\" ] && [ \"$2\" = \"redacted\" ]; then\n"
        "  echo '[gdrive]'\n"
        "  echo 'type = drive'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"lsf\" ]; then exit 0; fi\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_RCLONE_LOG\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def test_configure_writes_private_portable_config(tmp_path):
    local_root = tmp_path / "application storage" / "storage"
    local_root.mkdir(parents=True)
    config_file = tmp_path / "config.env"
    call_log = tmp_path / "calls.log"
    fake_rclone = _fake_rclone(tmp_path)

    env = os.environ.copy()
    env.update(
        {
            "RCLONE_BIN": str(fake_rclone),
            "SICTIC_RCLONE_CONFIG": str(config_file),
            "FAKE_RCLONE_LOG": str(call_log),
        }
    )
    result = subprocess.run(
        [
            str(REPO_ROOT / "rclone-sync" / "configure.sh"),
            "--local-root",
            str(local_root),
            "--remote",
            "gdrive:SICTIC-AI",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    content = config_file.read_text(encoding="utf-8")
    assert "RCLONE_LOCAL_ROOT=" in content
    assert "application\\ storage/storage" in content
    assert "RCLONE_REMOTE_ROOT=gdrive:SICTIC-AI" in content
    assert config_file.stat().st_mode & 0o777 == 0o600
    assert "/Users/openclaw" not in content


def test_bootstrap_dry_run_uses_google_drive_conversion_and_safety_flags(tmp_path):
    local_root = tmp_path / "storage"
    local_root.mkdir()
    call_log = tmp_path / "calls.log"
    fake_rclone = _fake_rclone(tmp_path)
    config_file = tmp_path / "config.env"
    config_file.write_text(
        f"RCLONE_BIN={fake_rclone}\n"
        f"RCLONE_LOCAL_ROOT={local_root}\n"
        "RCLONE_REMOTE_ROOT=gdrive:SICTIC-AI\n"
        f"RCLONE_WORK_DIR={tmp_path / 'state'}\n"
        f"RCLONE_RUN_LOG_DIR={tmp_path / 'run-logs'}\n"
        f"RCLONE_CENTRAL_LOG={tmp_path / 'rclone.log'}\n"
        f"RCLONE_LOCK_DIR={tmp_path / 'run.lock'}\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "SICTIC_RCLONE_CONFIG": str(config_file),
            "FAKE_RCLONE_LOG": str(call_log),
        }
    )
    result = subprocess.run(
        [str(REPO_ROOT / "rclone-sync" / "rclone-sync.sh"), "bootstrap-dry-run"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    args = call_log.read_text(encoding="utf-8")
    assert "bisync" in args
    assert "--resync --dry-run" in args
    assert "--drive-import-formats md" in args
    assert "--drive-export-formats md" in args
    assert "--max-delete 10" in args
    assert "--resilient" in args
    assert "--recover" in args

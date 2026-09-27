import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("rclone_status", [0, 17])
def test_sync_reports_logger_failure_and_preserves_rclone_failure(tmp_path, rclone_status):
    local_root = tmp_path / "storage"
    local_root.mkdir()
    (local_root / "RCLONE_TEST").touch()
    fake = tmp_path / "rclone"
    fake.write_text(f"#!/bin/sh\necho sync-output\nexit {rclone_status}\n")
    fake.chmod(0o755)
    # A directory cannot be opened as a log, even when tests run as root.
    central = tmp_path / "central.log"
    central.mkdir()
    config = tmp_path / "config.env"
    config.write_text(
        f"RCLONE_BIN={fake}\nRCLONE_LOCAL_ROOT={local_root}\n"
        "RCLONE_REMOTE_ROOT=gdrive:test\n"
        f"RCLONE_WORK_DIR={tmp_path / 'state'}\n"
        f"RCLONE_RUN_LOG_DIR={tmp_path / 'logs'}\n"
        f"RCLONE_CENTRAL_LOG={central}\n"
        f"RCLONE_LOCK_DIR={tmp_path / 'lock'}\n"
    )
    result = subprocess.run(
        [str(REPO_ROOT / "rclone-sync/rclone-sync.sh"), "sync"],
        capture_output=True, text=True, timeout=5,
        env={**os.environ, "SICTIC_RCLONE_CONFIG": str(config)},
    )
    assert result.returncode != 0
    if rclone_status:
        assert result.returncode == rclone_status
    assert str(central) in result.stderr
    assert "sync-output" in next((tmp_path / "logs").glob("*.log")).read_text()
    assert not (tmp_path / "lock").exists()


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


def test_sync_streams_before_completion_and_preserves_failure(tmp_path):
    import select
    import time

    local_root = tmp_path / "storage"
    local_root.mkdir()
    (local_root / "RCLONE_TEST").touch()
    release = tmp_path / "release"
    fake = tmp_path / "rclone"
    fake.write_text(
        '#!/bin/sh\necho "live stdout"\necho "live stderr" >&2\n'
        'while [ ! -f "$RELEASE_FILE" ]; do sleep 0.05; done\n'
        'echo "final output"\nexit 17\n'
    )
    fake.chmod(0o755)
    config = tmp_path / "config.env"
    central = tmp_path / "central.log"
    central.write_text("previous run\n")
    config.write_text(
        f"RCLONE_BIN={fake}\nRCLONE_LOCAL_ROOT={local_root}\n"
        "RCLONE_REMOTE_ROOT=gdrive:test\n"
        f"RCLONE_WORK_DIR={tmp_path / 'state'}\n"
        f"RCLONE_RUN_LOG_DIR={tmp_path / 'logs'}\n"
        f"RCLONE_CENTRAL_LOG={central}\n"
        f"RCLONE_LOCK_DIR={tmp_path / 'lock'}\n"
    )
    env = {**os.environ, "SICTIC_RCLONE_CONFIG": str(config), "RELEASE_FILE": str(release)}
    process = subprocess.Popen(
        [str(REPO_ROOT / "rclone-sync/rclone-sync.sh"), "sync"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
    )
    output = b""
    try:
        deadline = time.monotonic() + 5
        while b"live stderr\n" not in output:
            assert time.monotonic() < deadline, output
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                chunk = os.read(process.stdout.fileno(), 4096)
                assert chunk, output
                output += chunk
        assert process.poll() is None
        assert b"live stdout\n" in output
        # Both logs must receive the same output while rclone is still blocked.
        run_log = next((tmp_path / "logs").glob("*.log"))
        while "live stderr\n" not in central.read_text() or "live stderr\n" not in run_log.read_text():
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        release.touch()
        remaining, _ = process.communicate(timeout=5)
        output += remaining
    assert process.returncode == 17
    assert output.count(b"live stdout\n") == 1
    assert output.count(b"final output\n") == 1
    assert b"failed exit=17" in output
    assert run_log.read_bytes() == output
    assert central.read_bytes() == b"previous run\n" + output
    assert not (tmp_path / "lock").exists()

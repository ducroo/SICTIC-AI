import os
import subprocess
from pathlib import Path


HELPER = Path(__file__).resolve().parents[2] / "scripts" / "cloud-agent-dotenv-secrets.sh"


def _run_seed(tmp_path: Path, env_text: str, extra_env: dict[str, str]) -> str:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    script = tmp_path / "run.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "env_set() {\n"
        "  local key=\"$1\" value=\"$2\" path=\"$3\" tmp\n"
        "  tmp=\"${path}.tmp.$$\"\n"
        "  if grep -q \"^[[:space:]]*$key[[:space:]]*=\" \"$path\"; then\n"
        "    sed \"s/^\\\\([[:space:]]*$key[[:space:]]*=\\\\).*/\\\\1$value/\" \"$path\" > \"$tmp\"\n"
        "  else\n"
        "    cp \"$path\" \"$tmp\"\n"
        "    printf '%s=%s\\n' \"$key\" \"$value\" >> \"$tmp\"\n"
        "  fi\n"
        "  mv \"$tmp\" \"$path\"\n"
        "}\n"
        f"source '{HELPER}'\n"
        f"seed_dotenv_secrets '{env_file}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    env = os.environ.copy()
    env.pop("DEALUM_API_KEY", None)
    env.pop("DEALUM_DEALROOM_ID", None)
    env.update(extra_env)
    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return env_file.read_text(encoding="utf-8")


def test_seed_dotenv_secrets_writes_dealum_keys(tmp_path):
    text = _run_seed(
        tmp_path,
        "DEALUM_API_KEY=\nDEALUM_DEALROOM_ID=\n",
        {"DEALUM_API_KEY": "dealum-test-key", "DEALUM_DEALROOM_ID": "12345"},
    )
    assert "DEALUM_API_KEY=dealum-test-key" in text
    assert "DEALUM_DEALROOM_ID=12345" in text


def test_seed_dotenv_secrets_leaves_empty_keys_when_unset(tmp_path):
    text = _run_seed(
        tmp_path,
        "DEALUM_API_KEY=\nDEALUM_DEALROOM_ID=\n",
        {},
    )
    assert "DEALUM_API_KEY=\n" in text
    assert "DEALUM_DEALROOM_ID=\n" in text


def test_environment_yml_pins_onnxruntime_for_linux():
    yaml_text = (
        Path(__file__).resolve().parents[2] / "environment.yml"
    ).read_text(encoding="utf-8")
    assert "onnxruntime; platform_system != \"Darwin\"" in yaml_text

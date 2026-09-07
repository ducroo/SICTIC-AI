import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"

ASK_ENV_CALL = re.compile(
    r'^\s*ask_env\s+"(?P<key>[A-Z0-9_]+)"\s+".*?"\s+(?P<default>.+?)\s+'
    r'(?P<required>\S+)\s+(?P<secret>\S+)\s*$'
)


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"\n{name}() {{\n") + 1
    end = source.index("\n}\n", start) + len("\n}\n")
    return source[start:end]


def _harness(tmp_path: Path) -> Path:
    """Run install.sh's .env helpers on their own.

    The prompt helpers sit in the middle of a script that also builds a conda
    environment, so they are lifted out of the real file rather than copied:
    the test then fails if install.sh drifts away from what it asserts.
    """
    source = INSTALL_SH.read_text(encoding="utf-8")
    functions = "\n".join(
        _extract_function(source, name) for name in ("env_get", "env_set", "ask_env")
    )
    script = tmp_path / "ask_env_harness.sh"
    script.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'ENV_PATH="$1"\n'
        f"{functions}\n"
        'ask_env "$2" "prompt for $2" "$3" "$4" 0\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _run(script: Path, env_file: Path, key: str, default: str, required: str):
    return subprocess.run(
        [str(script), str(env_file), key, default, required],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


def test_required_prompt_without_default_fails_instead_of_looping(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=value\n", encoding="utf-8")
    script = _harness(tmp_path)

    result = _run(script, env_file, "CLOUD_TPM_BUDGET", "", "1")

    assert result.returncode != 0
    assert "CLOUD_TPM_BUDGET is required" in result.stderr
    assert "CLOUD_TPM_BUDGET" not in env_file.read_text(encoding="utf-8")


def test_supplied_default_answers_a_required_prompt(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=value\n", encoding="utf-8")
    script = _harness(tmp_path)

    result = _run(script, env_file, "CLOUD_TPM_BUDGET", "1000000", "1")

    assert result.returncode == 0, result.stderr
    assert "CLOUD_TPM_BUDGET=1000000" in env_file.read_text(encoding="utf-8")


def test_configured_value_survives_a_differing_default(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("CLOUD_TPM_BUDGET=250000\n", encoding="utf-8")
    script = _harness(tmp_path)

    result = _run(script, env_file, "CLOUD_TPM_BUDGET", "1000000", "1")

    assert result.returncode == 0, result.stderr
    assert "CLOUD_TPM_BUDGET=250000" in env_file.read_text(encoding="utf-8")


def test_every_ask_env_call_passes_boolean_required_and_secret_flags():
    """Guard the argument order of ask_env(key, prompt, default, required, secret).

    A default written into the `required` slot leaves the key required with no
    fallback value, which is how the CLOUD_TPM_BUDGET prompt could never be
    satisfied.
    """
    calls = []
    for line in INSTALL_SH.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("ask_env "):
            continue
        match = ASK_ENV_CALL.match(line)
        assert match, f"unparsed ask_env call: {line.strip()}"
        calls.append(match)

    assert calls, "no ask_env calls found in install.sh"
    for match in calls:
        key = match.group("key")
        assert match.group("required") in {"0", "1"}, f"{key}: required must be 0 or 1"
        assert match.group("secret") in {"0", "1"}, f"{key}: secret must be 0 or 1"

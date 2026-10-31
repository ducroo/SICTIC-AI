"""Guard that the Dealum integration only reads from Dealum."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEALUM_MODULES = [
    REPO_ROOT / "lib/infrastructure/dealum.py",
    *sorted((REPO_ROOT / "lib/startups/dealum").glob("*.py")),
    *sorted((REPO_ROOT / "skills/dealum_import").glob("*.py")),
    *sorted((REPO_ROOT / "skills/application_feedback").glob("*.py")),
]
READ_ONLY_METHODS = {"get", "head"}


def _http_calls(path: Path) -> list[str]:
    """Return the `requests.<name>` attributes and HTTP session uses in a module."""
    calls = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"requests", "httpx", "aiohttp", "urllib3"}
        ):
            calls.append(f"{node.value.id}.{node.attr}")
    return calls


def test_dealum_code_only_sends_get_and_head_requests():
    for path in DEALUM_MODULES:
        for call in _http_calls(path):
            library, method = call.split(".", 1)
            assert library == "requests" and method in READ_ONLY_METHODS, (
                f"{path.relative_to(REPO_ROOT)} uses {call}; the Dealum "
                "integration must stay read-only"
            )


def test_dealum_adapter_reads_applications():
    calls = _http_calls(REPO_ROOT / "lib/infrastructure/dealum.py")

    assert set(calls) == {"requests.get", "requests.head"}

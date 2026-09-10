import json

import pytest

from lib.infrastructure.configuration import (
    _local_cache_paths,
    config_cache_key,
    get_env_var,
    load_repository_config,
)
from lib.infrastructure.errors import InfrastructureError


def test_load_repository_config_builds_complete_tree():
    config = load_repository_config()

    assert "startup_profile" in config
    assert "query" in config["startup_profile"]
    assert "llm_instructions" in config["startup_profile"]


def test_load_repository_config_returns_requested_section():
    section = load_repository_config("startup_profile")

    assert "query" in section
    assert "llm_instructions" in section
    assert "startup_profile" not in section


def test_load_repository_config_returns_nested_value():
    query = load_repository_config("startup_profile", "query")

    assert isinstance(query, str)
    assert query


def test_configuration_cache_uses_local_data_path(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    local_data_root = tmp_path / "local-data"
    config_dir = repo_root / "config" / "demo"
    config_dir.mkdir(parents=True)
    (config_dir / "prompt.md").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("REPO_PATH", str(repo_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(local_data_root))

    config = load_repository_config("demo")

    assert config["prompt"] == "hello"
    assert _local_cache_paths()[1] == local_data_root / "cache" / "config.json"
    assert (local_data_root / "cache" / "config.json").is_file()
    assert not (repo_root / "cache" / "config.json").exists()


def test_load_repository_config_parses_json_files(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config" / "demo"
    config_dir.mkdir(parents=True)
    (config_dir / "prompt.md").write_text("Return JSON", encoding="utf-8")
    (config_dir / "response_schema.json").write_text(
        json.dumps({"type": "object", "required": ["result"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("REPO_PATH", str(repo_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path / "local-data"))

    config = load_repository_config("demo")

    assert config == {
        "prompt": "Return JSON",
        "response_schema": {
            "type": "object",
            "required": ["result"],
        },
    }


def test_load_repository_config_rejects_invalid_json(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config" / "demo"
    config_dir.mkdir(parents=True)
    (config_dir / "response_schema.json").write_text(
        '{"type": "object",}',
        encoding="utf-8",
    )
    monkeypatch.setenv("REPO_PATH", str(repo_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path / "local-data"))

    with pytest.raises(InfrastructureError, match="Invalid JSON configuration"):
        load_repository_config()


def test_load_repository_config_rejects_unknown_path():
    with pytest.raises(InfrastructureError, match="does not exist"):
        load_repository_config("not_a_real_section")


def test_config_cache_key_is_stable_for_equivalent_sections():
    first = {
        "prompt": "Return JSON",
        "response_schema": {"type": "object", "required": ["result"]},
    }
    second = {
        "response_schema": {"required": ["result"], "type": "object"},
        "prompt": "Return JSON",
    }

    assert config_cache_key(first) == config_cache_key(second)
    assert config_cache_key(first) != config_cache_key(
        {**first, "prompt": "Changed"}
    )


def test_get_env_var_rejects_missing_value(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_VARIABLE", raising=False)

    with pytest.raises(InfrastructureError, match="MISSING_TEST_VARIABLE"):
        get_env_var("MISSING_TEST_VARIABLE")


def test_get_env_var_rejects_blank_required_value(monkeypatch):
    monkeypatch.setenv("BLANK_TEST_VARIABLE", "  ")

    with pytest.raises(InfrastructureError, match="BLANK_TEST_VARIABLE"):
        get_env_var("BLANK_TEST_VARIABLE")


@pytest.mark.parametrize("value", [None, "", "  "])
def test_get_env_var_returns_none_for_absent_optional_value(
    monkeypatch,
    value,
):
    if value is None:
        monkeypatch.delenv("OPTIONAL_TEST_VARIABLE", raising=False)
    else:
        monkeypatch.setenv("OPTIONAL_TEST_VARIABLE", value)

    assert get_env_var("OPTIONAL_TEST_VARIABLE", required=False) is None


def test_get_env_var_returns_trimmed_optional_value(monkeypatch):
    monkeypatch.setenv("OPTIONAL_TEST_VARIABLE", " configured ")

    assert (
        get_env_var("OPTIONAL_TEST_VARIABLE", required=False)
        == "configured"
    )

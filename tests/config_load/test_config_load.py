import json

import pytest

from skills.config_load.config_load import (
    _local_cache_paths,
    config_key,
    config_load,
)


def test_config_load_builds_local_markdown_config():
    config = config_load()

    assert "startup_profile" in config
    assert "query" in config["startup_profile"]
    assert "llm_instructions" in config["startup_profile"]


def test_config_load_cache_uses_local_data_path(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    local_data_root = tmp_path / "local-data"
    config_dir = repo_root / "config" / "demo"
    config_dir.mkdir(parents=True)
    (config_dir / "prompt.md").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("REPO_PATH", str(repo_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(local_data_root))

    config = config_load()

    assert config["demo"]["prompt"] == "hello"
    assert _local_cache_paths()[1] == local_data_root / "cache" / "config.json"
    assert (local_data_root / "cache" / "config.json").is_file()
    assert not (repo_root / "cache" / "config.json").exists()


def test_config_load_parses_json_files(monkeypatch, tmp_path):
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

    config = config_load()

    assert config["demo"] == {
        "prompt": "Return JSON",
        "response_schema": {
            "type": "object",
            "required": ["result"],
        },
    }


def test_config_load_rejects_invalid_json(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config" / "demo"
    config_dir.mkdir(parents=True)
    (config_dir / "prompt.md").write_text("Return JSON", encoding="utf-8")
    (config_dir / "response_schema.json").write_text(
        '{"type": "object",}',
        encoding="utf-8",
    )
    monkeypatch.setenv("REPO_PATH", str(repo_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path / "local-data"))

    with pytest.raises(ValueError, match="Invalid JSON config file"):
        config_load()


def test_config_key_is_stable_for_equivalent_sections():
    first = {
        "prompt": "Return JSON",
        "response_schema": {"type": "object", "required": ["result"]},
    }
    second = {
        "response_schema": {"required": ["result"], "type": "object"},
        "prompt": "Return JSON",
    }

    assert config_key(first) == config_key(second)
    assert config_key(first) != config_key({**first, "prompt": "Changed"})

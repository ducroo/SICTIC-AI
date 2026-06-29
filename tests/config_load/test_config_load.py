from skills.config_load.config_load import config_load
from skills.config_load.config_load import _local_cache_paths


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

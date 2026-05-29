from skills.config_load.config_load import config_load


def test_config_load_builds_local_markdown_config():
    config = config_load()

    assert "startup_profile" in config
    assert "query" in config["startup_profile"]
    assert "llm_instructions" in config["startup_profile"]

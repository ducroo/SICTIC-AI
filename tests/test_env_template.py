import re
from pathlib import Path


def test_env_template_excludes_legacy_variables():
    template = Path(__file__).resolve().parents[1] / ".env-template"
    content = template.read_text(encoding="utf-8")

    legacy_keys = {
        "DEFAULT_LLM",
        "DEFAULT_EMBEDDINGS",
        "DEFAULT_VLM",
        "MAX_CONCURRENT_DOCLING",
        "MAX_CONCURRENT_EMBEDS",
        "MAX_CONCURRENT_LLMS",
        "OLLAMA_NUM_CTX",
        "OLLAMA_NUM_CTX_MAX",
        "REPO_DIR",
        "WORKSPACE_PATH",
        "WORKSPACE_DIR",
        "STORAGE_MIRROR_DIR",
        "STORAGE_MIRROR_PATH",
        "STORAGE_PATH",
        "STORAGE_PROVIDER",
        "SICTIC_SYNC_DAEMON",
    }

    for key in legacy_keys:
        assert not re.search(rf"^\s*{key}\s*=", content, re.MULTILINE)

from lib.insight_refresh import best_alternative, check_insight_refresh
from lib.storage import get_storage
from lib.storage_domains import dataset_raw_path


def test_best_alternative_uses_ranked_llms_order(monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b,ollama/gpt-5.4-mini")

    files = [
        "jane-doe-gpt-5-4-mini.md",
        "jane-doe-qwen3-8b.md",
        "jane-doe-gemma4-31b-nvfp4.md",
    ]

    assert list(best_alternative("jane-doe-gemma4-31b-nvfp4.md", files)) == [
        "jane-doe-qwen3-8b.md",
        "jane-doe-gpt-5-4-mini.md",
        "jane-doe-gemma4-31b-nvfp4.md",
    ]


def test_check_insight_refresh_returns_ranked_fresh_cache(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b,ollama/gpt-5.4-mini")
    storage = get_storage()

    source_file = f"{dataset_raw_path('avientus')}/source.md"
    target_dir = "insights/startups/avientus/person-profile"
    gpt_file = f"{target_dir}/jane-doe-gpt-5-4-mini.md"
    qwen_file = f"{target_dir}/jane-doe-qwen3-8b.md"

    storage.write_text(source_file, "source")
    storage.write_text(gpt_file, "gpt content")
    storage.write_text(qwen_file, "qwen content")

    storage.set_mtime(source_file, 100)
    storage.set_mtime(gpt_file, 200)
    storage.set_mtime(qwen_file, 200)

    assert check_insight_refresh(["avientus"], gpt_file) == (
        False,
        "qwen content",
        qwen_file,
    )


def test_check_insight_refresh_requests_refresh_when_cache_is_stale(mock_env):
    storage = get_storage()

    source_file = f"{dataset_raw_path('avientus')}/source.md"
    target_file = "insights/startups/avientus/person-profile/jane-doe-gpt-5-4-mini.md"

    storage.write_text(source_file, "source")
    storage.write_text(target_file, "cached")

    storage.set_mtime(source_file, 200)
    storage.set_mtime(target_file, 100)

    assert check_insight_refresh(["avientus"], target_file) == (True, None, None)

from lib.insight_refresh import best_alternative, check_insight_refresh, ranked_alternatives
from lib.storage import get_storage
from lib.storage_domains import dataset_location_for_domain, dataset_raw_path


def _create_avientus():
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )


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


def test_ranked_alternatives_only_yields_ranked_models_without_provider(monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "qwen3:8b")

    files = [
        "jane-doe-gpt-5-4-mini.md",
        "jane-doe-qwen3-8b.md",
        "jane-doe-gemma4-31b-nvfp4.md",
    ]

    assert list(ranked_alternatives("jane-doe-gpt-5-4-mini.md", files)) == [
        "jane-doe-qwen3-8b.md",
    ]


def test_check_insight_refresh_returns_ranked_fresh_cache(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b,ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_avientus()

    source_file = f"{dataset_raw_path('avientus')}/source.md"
    target_dir = "storage/startups/avientus/insights/person-profile"
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


def test_check_insight_refresh_ignores_unranked_fresh_cache(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b")
    storage = get_storage()
    _create_avientus()

    source_file = f"{dataset_raw_path('avientus')}/source.md"
    unranked_file = "storage/startups/avientus/insights/person-profile/jane-doe-gemma4-31b-nvfp4.md"

    storage.write_text(source_file, "source")
    storage.write_text(unranked_file, "gemma content")

    storage.set_mtime(source_file, 100)
    storage.set_mtime(unranked_file, 200)

    assert check_insight_refresh(["avientus"], unranked_file) == (True, None, None)


def test_check_insight_refresh_requests_refresh_when_cache_is_stale(mock_env):
    storage = get_storage()
    _create_avientus()

    source_file = f"{dataset_raw_path('avientus')}/source.md"
    target_file = "storage/startups/avientus/insights/person-profile/jane-doe-gpt-5-4-mini.md"

    storage.write_text(source_file, "source")
    storage.write_text(target_file, "cached")

    storage.set_mtime(source_file, 200)
    storage.set_mtime(target_file, 100)

    assert check_insight_refresh(["avientus"], target_file) == (True, None, None)

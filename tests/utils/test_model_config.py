from lib.model_config import embedding_endpoint, llm_endpoint


def test_llm_endpoint_prefers_explicit_llm_vars(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "llm-key")

    endpoint = llm_endpoint()

    assert endpoint.model == "openai/gpt-4.1-mini"
    assert endpoint.base_url == "https://llm.example.test/v1"
    assert endpoint.api_key == "llm-key"
    assert endpoint.litellm_kwargs() == {
        "model": "openai/gpt-4.1-mini",
        "api_base": "https://llm.example.test/v1",
        "api_key": "llm-key",
    }


def test_embedding_endpoint_prefers_explicit_embedding_vars(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embed.example.test/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "embed-key")

    endpoint = embedding_endpoint()

    assert endpoint.model == "openai/text-embedding-3-small"
    assert endpoint.base_url == "https://embed.example.test/v1"
    assert endpoint.api_key == "embed-key"


def test_ollama_endpoint_uses_ollama_host_when_base_url_is_blank(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen3:8b")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.example.test:11434")

    endpoint = llm_endpoint()

    assert endpoint.model == "ollama/qwen3:8b"
    assert endpoint.base_url == "http://ollama.example.test:11434"


def test_llm_endpoint_falls_back_to_openai_api_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")

    endpoint = llm_endpoint()

    assert endpoint.api_key == "openai-secret"
    assert endpoint.base_url is None


def test_embedding_endpoint_falls_back_to_openrouter_api_key(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "openrouter/openai/text-embedding-3-small")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")

    endpoint = embedding_endpoint()

    assert endpoint.api_key == "openrouter-secret"
    assert endpoint.base_url is None

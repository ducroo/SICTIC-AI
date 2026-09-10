from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from lib.infrastructure.configuration import get_env_var


@dataclass(frozen=True)
class ModelEndpoint:
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None

    def litellm_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"model": self.model}
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return kwargs


def _optional_env(name: str) -> Optional[str]:
    return get_env_var(name, required=False)


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = _optional_env(name)
        if value:
            return value
    return None


def _base_url_for_model(model: str, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    if model.startswith("ollama/"):
        return _first_env("OLLAMA_HOST") or "http://localhost:11434"
    return None


def llm_endpoint() -> ModelEndpoint:
    model = get_env_var("LLM_MODEL")
    return ModelEndpoint(
        model=model,
        base_url=_base_url_for_model(model, _first_env("LLM_BASE_URL")),
        # OPENAI_API_KEY is the common Cloud Agent / provider secret name.
        api_key=_first_env("LLM_API_KEY", "OPENAI_API_KEY"),
    )


def embedding_endpoint() -> ModelEndpoint:
    model = get_env_var("EMBEDDING_MODEL")
    return ModelEndpoint(
        model=model,
        base_url=_base_url_for_model(model, _first_env("EMBEDDING_BASE_URL")),
        # OpenRouter embeddings may use EMBEDDING_API_KEY or OPENROUTER_API_KEY.
        api_key=_first_env("EMBEDDING_API_KEY", "OPENROUTER_API_KEY"),
    )


def rerank_endpoint() -> Optional[ModelEndpoint]:
    """Cross-encoder reranking endpoint, or None when reranking is disabled."""
    model = get_env_var("RERANK_MODEL", required=False)
    if not model:
        return None
    return ModelEndpoint(
        model=model,
        base_url=_first_env("RERANK_BASE_URL"),
        api_key=_first_env("RERANK_API_KEY"),
    )


def llm_model() -> str:
    return llm_endpoint().model


def embedding_model() -> str:
    return embedding_endpoint().model

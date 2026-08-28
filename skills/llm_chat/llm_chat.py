import hashlib
import math
from typing import Dict, Any, Optional
from lib.runtime_noise import configure_runtime_noise

configure_runtime_noise()

from litellm.exceptions import APIConnectionError
from lib.llm_timeouts import (
    effective_request_timeout,
    structured_num_predict,
)
from lib.services_gateway import gateway
from lib.env import get_env_var
from lib.logger import get_logger
from lib.model_config import llm_endpoint

logger = get_logger(__name__)


def _supports_explicit_prompt_caching(model: str) -> bool:
    if model.startswith(("ollama/", "mlx/")):
        return False
    return model.rsplit("/", 1)[-1].startswith("gpt-5.6")


def ollama_format_from_response_format(response_format: Any) -> dict | str:
    """Map LiteLLM json_schema payloads onto Ollama's native format field."""
    if isinstance(response_format, dict):
        schema = None
        if response_format.get("type") == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema")
        if isinstance(schema, dict) and schema:
            return schema
    return "json"


def apply_ollama_structured_options(
    kwargs: dict[str, Any],
    response_format: Any,
) -> None:
    """Constrain local JSON calls: no thinking, native schema, bounded decode."""
    kwargs["think"] = False
    kwargs["format"] = ollama_format_from_response_format(response_format)
    kwargs["num_predict"] = structured_num_predict()
    kwargs.pop("response_format", None)


async def llm_chat(
    prompt: str,
    response_format: Optional[Any] = None,
    cacheable_prompt_prefix: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Optional[str]:
    endpoint = llm_endpoint()
    default_model = endpoint.model
    is_ollama = default_model.startswith("ollama/")
    full_prompt = f"{cacheable_prompt_prefix or ''}{prompt}"

    min_ctx = int(get_env_var("OLLAMA_CONTEXT_LENGTH"))
    max_ctx = int(get_env_var("OLLAMA_CONTEXT_LENGTH_MAX"))
    estimated_tokens = int(len(full_prompt) / 3)

    if estimated_tokens > max_ctx:
        logger.warning(f"Prompt is too long ({estimated_tokens} tokens > {max_ctx}). Truncating the first part.")
        # Fix truncation logic: keep the END of the prompt (where the instructions usually are)
        full_prompt = full_prompt[-(3 * max_ctx):]
        prompt = full_prompt
        cacheable_prompt_prefix = None
        estimated_tokens = max_ctx

    if estimated_tokens <= min_ctx:
        ctx = min_ctx
    else:
        # Snap to the next power of 2 (Buddy Memory Allocation)
        power_of_2 = int(2 ** math.ceil(math.log2(estimated_tokens)))
        ctx = max(min_ctx, min(max_ctx, power_of_2))

    use_explicit_cache = bool(
        cacheable_prompt_prefix
        and _supports_explicit_prompt_caching(default_model)
    )
    if use_explicit_cache:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": cacheable_prompt_prefix,
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
    else:
        messages = [{"role": "user", "content": full_prompt}]
    kwargs: Dict[str, Any] = endpoint.litellm_kwargs()
    kwargs.update(
        {
            "messages": messages,
            "timeout": effective_request_timeout(
                structured=response_format is not None,
                override=timeout,
            ),
        }
    )

    if use_explicit_cache:
        # LiteLLM 1.97 still drops prompt_cache_key when supplied as a named
        # argument, while its extra_body passthrough preserves the complete
        # GPT-5.6 request. The request shape is covered by tests.
        cache_digest = hashlib.sha256(
            cacheable_prompt_prefix.encode("utf-8")
        ).hexdigest()[:32]
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body.update(
            {
                "prompt_cache_key": f"sictic-ai:{cache_digest}",
                "prompt_cache_options": {"mode": "explicit"},
            }
        )
        kwargs["extra_body"] = extra_body

    if response_format:
        if is_ollama:
            apply_ollama_structured_options(kwargs, response_format)
        else:
            kwargs["response_format"] = response_format

    if is_ollama:
        kwargs["num_ctx"] = ctx

    logger.info(f"Sending request to {default_model} with context {ctx} (estimated tokens: {estimated_tokens})...")
    try:
        response = await gateway.request_completion(kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info("LLM usage for %s: %s", default_model, usage)
        content = response.choices[0].message.content
        if not content:
            logger.warning("Received an empty response from the model.")
        return content
    except APIConnectionError as e:
        logger.error(f"API Connection Error: Could not connect to {default_model}. {e}")
        raise e
    except Exception as e:
        error_msg = str(e).lower()
        if "not found" in error_msg or "model" in error_msg:
             logger.error(f"Model Error: The model '{default_model}' was not found or is unsupported. {e}")
        else:
            logger.error(f"An unexpected error occurred: {e}")
        raise e

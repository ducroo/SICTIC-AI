import math
from typing import Dict, Any, Optional
from lib.runtime_noise import configure_runtime_noise

configure_runtime_noise()

from litellm.exceptions import APIConnectionError
from lib.services_gateway import gateway
from lib.env import get_env_var
from lib.logger import get_logger
from lib.model_config import llm_endpoint

logger = get_logger(__name__)

async def llm_chat(prompt: str, response_format: Optional[Any] = None) -> Optional[str]:
    endpoint = llm_endpoint()
    default_model = endpoint.model
    is_ollama = default_model.startswith("ollama/")

    min_ctx = int(get_env_var("OLLAMA_CONTEXT_LENGTH"))
    max_ctx = int(get_env_var("OLLAMA_CONTEXT_LENGTH_MAX"))
    estimated_tokens = int(len(prompt) / 3)

    if estimated_tokens > max_ctx:
        logger.warning(f"Prompt is too long ({estimated_tokens} tokens > {max_ctx}). Truncating the first part.")
        # Fix truncation logic: keep the END of the prompt (where the instructions usually are)
        prompt = prompt[-(3 * max_ctx):]
        estimated_tokens = max_ctx

    if estimated_tokens <= min_ctx:
        ctx = min_ctx
    else:
        # Snap to the next power of 2 (Buddy Memory Allocation)
        power_of_2 = int(2 ** math.ceil(math.log2(estimated_tokens)))
        ctx = max(min_ctx, min(max_ctx, power_of_2))

    messages = [{"role": "user", "content": prompt}]
    kwargs: Dict[str, Any] = endpoint.litellm_kwargs()
    kwargs.update({"messages": messages, "timeout": 3600.0})
    
    if response_format:
        kwargs["response_format"] = response_format

    if is_ollama:
        kwargs["num_ctx"] = ctx
    
    logger.info(f"Sending request to {default_model} with context {ctx} (estimated tokens: {estimated_tokens})...")
    try:
        response = await gateway.request_completion(kwargs)
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

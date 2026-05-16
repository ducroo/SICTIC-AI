from typing import Dict, Any, Optional
import litellm
from litellm.exceptions import APIConnectionError
from lib.services_gateway import gateway, Priority
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)



async def llm_chat(prompt: str, response_format: Optional[Any] = None) -> Optional[str]:
    default_model = get_env_var("DEFAULT_LLM")
    is_ollama = default_model.startswith("ollama/")

    min_ctx=int(get_env_var("OLLAMA_CONTEXT_LENGTH"))
    max_ctx= int(get_env_var("OLLAMA_MAX_CONTEXT"))
    ctx =int(len(prompt)/3)

    if ctx > max_ctx:
        logger.warning(f"Prompt is too long ({ctx*3} characters > 100'000). Truncating the first part.")
        prompt = prompt[(3*max_ctx):]
        ctx=max_ctx

    messages = [{"role": "user", "content": prompt}]
    kwargs: Dict[str, Any] = {"model": default_model, "messages": messages, "timeout": 3600.0}
    
    if response_format:
        if not is_ollama:
            kwargs["response_format"] = response_format

    if is_ollama:
        kwargs["api_base"] = get_env_var("OLLAMA_HOST")
        if ctx>min_ctx:
            kwargs["num_ctx"] = ctx
    
    logger.info(f"Sending request to {default_model}...")
    try:
        response = await gateway.request_completion(kwargs, priority=Priority.STANDARD)
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

"""Provider-neutral Markdown and JSON generation with shared recovery."""

from __future__ import annotations

import hashlib
import math
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from lib.infrastructure.ai_text_generation.json import (
    add_temporary_reasoning_field,
    json_schema_response_format,
    parse_json_response,
    remove_temporary_reasoning,
    schema_prompt_block,
    validate_json_schema,
    validate_schema,
)
from lib.infrastructure.ai_text_generation.measurements import (
    active_local_jobs,
    measurements_enabled,
    record_attempt,
)
from lib.infrastructure.ai_text_generation.types import Review
from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from lib.infrastructure.logging import get_logger
from lib.infrastructure.retry import with_rate_limit_retry
from lib.infrastructure.scheduler import scheduler
from lib.infrastructure.scheduler_operations import (
    JobProfile,
    register_operation,
)
from lib.model_config import ModelEndpoint, llm_endpoint


logger = get_logger(__name__)

MAX_MARKDOWN_ATTEMPTS = 3
MAX_JSON_ATTEMPTS = 2
_DEFAULT_REQUEST_TIMEOUT = 1200.0
T = TypeVar("T", str, dict, list)
Reviewer = Callable[[T], Review[T]]


def _is_transient_provider_error(error: BaseException) -> bool:
    """Rate limits (429) and provider overload/outage (503 and friends):
    the request never ran — waiting beats failing."""
    return isinstance(error, InfrastructureError) and error.kind in (
        InfrastructureErrorKind.RATE_LIMIT,
        InfrastructureErrorKind.SERVICE_UNAVAILABLE,
    )


async def _request_text_waiting_out_rate_limits(**kwargs: Any) -> str:
    """One logical attempt: 429s/503s wait for the provider to recover,
    they don't count as failed generation attempts (the request never
    ran)."""
    return await with_rate_limit_retry(
        lambda: _request_text(**kwargs),
        is_rate_limit=_is_transient_provider_error,
        logger=logger,
        label=f"{kwargs.get('output_type', 'text')} generation",
    )


@dataclass
class _RequestRuntime:
    provider_started_at: float | None = None
    concurrent_local_jobs: int | None = None
    context_size: int | None = None
    provider_kwargs: dict[str, Any] = field(default_factory=dict)


async def generate_markdown(
    prompt: str,
    reviewer: Reviewer[str] | None = None,
    *,
    cacheable_prompt_prefix: str | None = None,
) -> str:
    """Generate one non-empty Markdown response."""
    prompt = _required_prompt(prompt)
    request_id = str(uuid.uuid4())
    errors: list[str] = []
    feedback = ""
    for attempt in range(1, MAX_MARKDOWN_ATTEMPTS + 1):
        try:
            output = (
                await _request_text_waiting_out_rate_limits(
                    prompt=prompt + feedback,
                    output_type="markdown",
                    attempt=attempt,
                    request_id=request_id,
                    cacheable_prompt_prefix=cacheable_prompt_prefix,
                )
            ).strip()
            if not output:
                raise _RejectedOutput("The model returned no Markdown")
            if reviewer is not None:
                review = _run_reviewer(reviewer, output)
                output = review.output.strip()
                if not output:
                    raise _RejectedOutput(
                        "The reviewer produced empty Markdown"
                    )
                if review.problems:
                    raise _RejectedOutput("; ".join(review.problems))
            return output
        except _RejectedOutput as error:
            errors.append(str(error))
        except InfrastructureError as error:
            if not error.recoverable:
                raise
            errors.append(str(error))
        if attempt < MAX_MARKDOWN_ATTEMPTS:
            logger.warning(
                "Markdown generation attempt %d/%d failed; retrying: %s",
                attempt,
                MAX_MARKDOWN_ATTEMPTS,
                errors[-1],
            )
            feedback = _correction_feedback(errors[-1], output="Markdown")
    raise _exhausted_error("generate_markdown", errors)


async def generate_json(
    prompt: str,
    schema: dict[str, Any],
    reviewer: Reviewer[dict | list] | None = None,
    *,
    cacheable_prompt_prefix: str | None = None,
) -> dict | list:
    """Generate, technically validate, and optionally review one JSON value."""
    prompt = _required_prompt(prompt)
    request_id = str(uuid.uuid4())
    if not isinstance(schema, dict):
        raise TypeError("schema must be a dictionary")
    validate_schema(schema)
    if cacheable_prompt_prefix:
        effective_prefix = cacheable_prompt_prefix.rstrip() + "\n\n"
    else:
        effective_prefix = None

    errors: list[str] = []
    feedback = ""
    for attempt in range(1, MAX_JSON_ATTEMPTS + 1):
        if attempt == 1:
            attempt_schema = schema
            wrapped_reasoning = False
            thinking = True
            reasoning_instruction = ""
        else:
            attempt_schema, wrapped_reasoning = (
                add_temporary_reasoning_field(schema)
            )
            thinking = False
            reasoning_instruction = (
                "\n\nThe response schema contains a temporary `reasoning` "
                "field. Generate that field first and use it as working "
                "notes before generating the remaining fields. Return only "
                "the JSON object."
            )
        effective_prompt = (
            schema_prompt_block(attempt_schema)
            + "\n\n"
            + prompt
            + reasoning_instruction
        )
        response_format = json_schema_response_format(attempt_schema)
        try:
            raw_output = await _request_text_waiting_out_rate_limits(
                prompt=effective_prompt + feedback,
                output_type="json",
                attempt=attempt,
                request_id=request_id,
                response_format=response_format,
                cacheable_prompt_prefix=effective_prefix,
                thinking=thinking,
            )
            try:
                output = parse_json_response(raw_output, attempt_schema)
                if attempt == 2:
                    output = remove_temporary_reasoning(
                        output,
                        wrapped=wrapped_reasoning,
                    )
                    validate_json_schema(
                        output,
                        schema,
                        label="AI response after removing temporary reasoning",
                    )
            except ValueError as error:
                raise _RejectedOutput(str(error)) from error
            if reviewer is not None:
                review = _run_reviewer(reviewer, output)
                try:
                    validate_json_schema(
                        review.output,
                        schema,
                        label="Reviewed AI response",
                    )
                except ValueError as error:
                    raise _RejectedOutput(str(error)) from error
                output = review.output
                if review.problems:
                    raise _RejectedOutput("; ".join(review.problems))
            return output
        except _RejectedOutput as error:
            errors.append(str(error))
        except InfrastructureError as error:
            if not error.recoverable:
                raise
            errors.append(str(error))
        if attempt < MAX_JSON_ATTEMPTS:
            logger.warning(
                "JSON generation attempt %d/%d failed; retrying: %s",
                attempt,
                MAX_JSON_ATTEMPTS,
                errors[-1],
            )
            feedback = _correction_feedback(errors[-1], output="JSON")
    raise _exhausted_error("generate_json", errors)


def _run_reviewer(reviewer: Reviewer[T], output: T) -> Review[T]:
    review = reviewer(output)
    if not isinstance(review, Review):
        raise TypeError("reviewer must return Review")
    if not isinstance(review.problems, tuple) or any(
        not isinstance(problem, str) or not problem.strip()
        for problem in review.problems
    ):
        raise TypeError("review problems must be non-empty strings")
    return review


async def _request_text(
    prompt: str,
    *,
    output_type: str,
    attempt: int,
    request_id: str,
    response_format: dict[str, Any] | None = None,
    cacheable_prompt_prefix: str | None = None,
    thinking: bool | None = None,
) -> str:
    endpoint = llm_endpoint()
    model = endpoint.model
    full_prompt = f"{cacheable_prompt_prefix or ''}{prompt}"
    request_timeout = _request_timeout()
    runtime = _RequestRuntime()

    logger.info(
        "Requesting AI text from %s (%s input characters)",
        model,
        len(full_prompt),
    )

    scheduled_at = time.monotonic()
    response: Any = None
    content = ""
    status = "failed"
    error_kind: str | None = None

    try:
        response = await scheduler.run(
            _complete_text_request,
            operation_kwargs={
                "endpoint": endpoint,
                "prompt": prompt,
                "output_type": output_type,
                "attempt": attempt,
                "cacheable_prompt_prefix": cacheable_prompt_prefix,
                "response_format": response_format,
                "thinking": thinking,
                "timeout": request_timeout,
                "runtime": runtime,
            },
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info("AI text usage for %s: %s", model, usage)
        content = response.choices[0].message.content or ""
        status = "completed"
        return content or ""
    except InfrastructureError as error:
        error_kind = error.kind.value
        if error.kind in {
            InfrastructureErrorKind.TIMEOUT,
            InfrastructureErrorKind.RESOURCE_BUSY,
        }:
            status = "timed_out"
        raise
    except Exception as error:
        translated = _translate_provider_error(model, error)
        error_kind = translated.kind.value
        if translated.kind is InfrastructureErrorKind.TIMEOUT:
            status = "timed_out"
        raise translated from error
    finally:
        finished_at = time.monotonic()
        provider_duration = (
            finished_at - runtime.provider_started_at
            if runtime.provider_started_at is not None
            else None
        )
        message = None
        if response is not None:
            try:
                message = response.choices[0].message
            except (AttributeError, IndexError, KeyError, TypeError):
                message = None
        reasoning = getattr(message, "reasoning_content", None)
        record_attempt(
            request_id=request_id,
            model=model,
            output_type=output_type,
            attempt=attempt,
            input_characters=len(full_prompt),
            output_characters=len(content),
            reasoning_characters=(
                len(reasoning) if isinstance(reasoning, str) else None
            ),
            context_size=runtime.context_size,
            thinking_enabled=_explicit_thinking_setting(
                runtime.provider_kwargs
            ),
            timeout_seconds=request_timeout,
            concurrent_local_jobs=runtime.concurrent_local_jobs,
            scheduler_wait_seconds=(
                runtime.provider_started_at - scheduled_at
                if runtime.provider_started_at is not None
                else None
            ),
            provider_duration_seconds=provider_duration,
            total_duration_seconds=finished_at - scheduled_at,
            status=status,
            error_kind=error_kind,
            response=response,
        )


def _explicit_thinking_setting(kwargs: dict[str, Any]) -> bool | None:
    """Return an explicitly requested thinking mode, if one was supplied."""
    value = kwargs.get("think")
    if isinstance(value, bool):
        return value
    extra_body = kwargs.get("extra_body")
    if isinstance(extra_body, dict):
        value = extra_body.get("think")
        if isinstance(value, bool):
            return value
    return None


async def _completion(kwargs: dict[str, Any]) -> Any:
    import litellm

    litellm.disable_aiohttp_transport = True
    return await litellm.acompletion(**kwargs)


async def _complete_text_request(
    *,
    endpoint: ModelEndpoint,
    prompt: str,
    output_type: str,
    attempt: int,
    cacheable_prompt_prefix: str | None,
    response_format: dict[str, Any] | None,
    thinking: bool | None,
    timeout: float,
    runtime: _RequestRuntime,
) -> Any:
    """Execute one provider request; scheduling metadata uses these arguments."""
    del output_type, attempt
    model = endpoint.model
    messages, extra_body = _messages(
        prompt,
        model=model,
        cacheable_prompt_prefix=cacheable_prompt_prefix,
    )
    kwargs = endpoint.litellm_kwargs()
    kwargs.update({"messages": messages, "timeout": timeout})
    if extra_body:
        kwargs["extra_body"] = extra_body
    if response_format is not None:
        kwargs["response_format"] = response_format

    if model.startswith("ollama/"):
        runtime.context_size = _ollama_context(
            len(cacheable_prompt_prefix or "") + len(prompt)
        )
        kwargs["num_ctx"] = runtime.context_size
        if thinking is not None:
            kwargs["think"] = thinking
    runtime.provider_kwargs = kwargs
    runtime.provider_started_at = time.monotonic()
    if measurements_enabled():
        try:
            runtime.concurrent_local_jobs = active_local_jobs(
                scheduler.snapshot()
            )
        except Exception:
            runtime.concurrent_local_jobs = None
    return await _completion(kwargs)


def _messages(
    prompt: str,
    *,
    model: str,
    cacheable_prompt_prefix: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not cacheable_prompt_prefix or not _supports_explicit_cache(model):
        return [
            {
                "role": "user",
                "content": f"{cacheable_prompt_prefix or ''}{prompt}",
            }
        ], None
    return [
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
    ], {
        "prompt_cache_key": _prompt_cache_key(cacheable_prompt_prefix),
        "prompt_cache_options": {"mode": "explicit"},
    }


def _prompt_cache_key(cacheable_prompt_prefix: str) -> str:
    digest = hashlib.sha256(
        cacheable_prompt_prefix.encode("utf-8")
    ).hexdigest()[:32]
    return f"sictic-ai:{digest}"


def _inspect_text_request(kwargs: Mapping[str, Any]) -> JobProfile:
    endpoint = kwargs["endpoint"]
    if not isinstance(endpoint, ModelEndpoint):
        raise TypeError("Text request endpoint must be a ModelEndpoint")
    prompt = str(kwargs["prompt"])
    prefix = str(kwargs.get("cacheable_prompt_prefix") or "")
    output_type = str(kwargs["output_type"])
    return JobProfile(
        kind=f"llm_{output_type}",
        descriptor=endpoint.model,
        input_size=len(prefix) + len(prompt),
        cached_input_size=len(prefix),
        affinity_key=_prompt_cache_key(prefix) if prefix else None,
        parameters={
            "output_type": output_type,
            "attempt": int(kwargs["attempt"]),
            "structured": kwargs.get("response_format") is not None,
        },
    )


register_operation(_complete_text_request, _inspect_text_request)


def _supports_explicit_cache(model: str) -> bool:
    if model.startswith(("ollama/", "mlx/")):
        return False
    return model.rsplit("/", 1)[-1].startswith("gpt-5.6")


def _ollama_context(input_characters: int) -> int:
    minimum = _positive_int_env("OLLAMA_CONTEXT_LENGTH")
    maximum = _positive_int_env("OLLAMA_CONTEXT_LENGTH_MAX")
    if minimum > maximum:
        raise InfrastructureError(
            "OLLAMA_CONTEXT_LENGTH cannot exceed "
            "OLLAMA_CONTEXT_LENGTH_MAX",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="ai_text_generation",
            operation="prepare_request",
        )
    estimated_tokens = max(1, math.ceil(input_characters / 3))
    if estimated_tokens > maximum:
        raise InfrastructureError(
            f"Prompt estimate {estimated_tokens} tokens exceeds the "
            f"configured Ollama maximum of {maximum}; the prompt was not "
            "truncated",
            kind=InfrastructureErrorKind.DATA_INTEGRITY,
            provider="ai_text_generation",
            operation="prepare_request",
        )
    if estimated_tokens <= minimum:
        return minimum
    return min(
        maximum,
        2 ** math.ceil(math.log2(estimated_tokens)),
    )


def _positive_int_env(name: str) -> int:
    raw = get_env_var(name)
    try:
        value = int(raw)
    except ValueError as error:
        raise InfrastructureError(
            f"Environment variable {name!r} must be an integer",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="ai_text_generation",
            operation="load_configuration",
        ) from error
    if value < 1:
        raise InfrastructureError(
            f"Environment variable {name!r} must be positive",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="ai_text_generation",
            operation="load_configuration",
        )
    return value


def _request_timeout() -> float:
    raw = get_env_var("LLM_REQUEST_TIMEOUT", required=False)
    if raw is None:
        return _DEFAULT_REQUEST_TIMEOUT
    try:
        value = float(raw)
    except ValueError as error:
        raise InfrastructureError(
            "LLM_REQUEST_TIMEOUT must be numeric",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="ai_text_generation",
            operation="load_configuration",
        ) from error
    if value <= 0:
        raise InfrastructureError(
            "LLM_REQUEST_TIMEOUT must be positive",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="ai_text_generation",
            operation="load_configuration",
        )
    return value


def _required_prompt(prompt: str) -> str:
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("prompt must not be empty")
    return prompt


def _correction_feedback(problem: str, *, output: str) -> str:
    return (
        "\n\n### CORRECTION REQUIRED\n\n"
        f"Your previous response was invalid: {problem}\n"
        f"Try again and return only valid {output}."
    )


def _exhausted_error(
    operation: str,
    errors: list[str],
) -> InfrastructureError:
    return InfrastructureError(
        f"Failed after {len(errors)} attempts: " + " | ".join(errors),
        kind=InfrastructureErrorKind.INVALID_RESPONSE,
        provider="ai_text_generation",
        operation=operation,
    )


def _translate_provider_error(
    model: str,
    error: Exception,
) -> InfrastructureError:
    from litellm import exceptions

    mappings = (
        (
            exceptions.AuthenticationError,
            InfrastructureErrorKind.AUTHENTICATION,
        ),
        (
            exceptions.PermissionDeniedError,
            InfrastructureErrorKind.PERMISSION_DENIED,
        ),
        (exceptions.RateLimitError, InfrastructureErrorKind.RATE_LIMIT),
        (exceptions.Timeout, InfrastructureErrorKind.TIMEOUT),
        (
            (
                exceptions.APIConnectionError,
                exceptions.BadGatewayError,
                exceptions.InternalServerError,
                exceptions.ServiceUnavailableError,
            ),
            InfrastructureErrorKind.SERVICE_UNAVAILABLE,
        ),
        (
            (
                exceptions.BadRequestError,
                exceptions.ContextWindowExceededError,
                exceptions.InvalidRequestError,
                exceptions.JSONSchemaValidationError,
                exceptions.UnprocessableEntityError,
                exceptions.UnsupportedParamsError,
            ),
            InfrastructureErrorKind.INVALID_RESPONSE,
        ),
        (exceptions.NotFoundError, InfrastructureErrorKind.CONFIGURATION),
    )
    kind = InfrastructureErrorKind.SERVICE_UNAVAILABLE
    for error_types, candidate in mappings:
        if isinstance(error, error_types):
            kind = candidate
            break
    return InfrastructureError(
        str(error),
        kind=kind,
        provider=model,
        operation="generate_text",
        recoverable=(
            True
            if isinstance(error, exceptions.JSONSchemaValidationError)
            else None
        ),
    )


class _RejectedOutput(ValueError):
    pass

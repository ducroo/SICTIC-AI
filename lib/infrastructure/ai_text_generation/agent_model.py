"""Model for agent runs with the OpenAI Agents SDK, through LiteLLM and the shared scheduler.

Every model call of an agent waits for the shared scheduler like the calls of
generate_markdown and generate_json. So parallel agent runs stay within the
cloud token budget (CLOUD_TPM_BUDGET) and the local model capacity.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agents import ModelRetrySettings, ModelSettings, retry_policies
from agents.extensions.models.litellm_model import LitellmModel

from lib.infrastructure.scheduler import scheduler
from lib.infrastructure.scheduler_operations import JobProfile, register_operation
from lib.model_config import llm_endpoint


class TokenBudgetExceeded(RuntimeError):
    """An agent run used more tokens than its limit."""


@dataclass
class TokenUsage:
    """Model usage of one agent run, across all its agents."""

    requests: int = 0
    input_tokens: int = 0
    # Part of input_tokens the provider served from its prompt cache, at a lower price.
    cached_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def agent_model_settings(request_timeout_seconds: float) -> ModelSettings:
    """Return the model settings of an agent: usage reporting, timeout and retries.

    Args:
        request_timeout_seconds: Longest time one model call may take before it
            is cancelled and sent again.
    """
    return ModelSettings(
        include_usage=True,
        timeout=request_timeout_seconds,
        # Rate limits, timeouts and short provider outages wait and retry
        # instead of ending a long run whose tokens are already billed.
        retry=ModelRetrySettings(
            max_retries=6,
            backoff={"initial_delay": 5, "max_delay": 120, "multiplier": 2, "jitter": True},
            policy=retry_policies.any(
                retry_policies.provider_suggested(),
                retry_policies.retry_after(),
                retry_policies.http_status([429, 500, 502, 503, 504]),
                retry_policies.network_error(),
            ),
        ),
    )


async def _agent_model_request(
    *,
    descriptor: str,
    input_size: int,
    request: Callable[[], Awaitable[Any]],
) -> Any:
    """Send one model request of an agent; the scheduler reads descriptor and input_size."""
    del descriptor, input_size
    return await request()


def _inspect_agent_model_request(kwargs: Mapping[str, Any]) -> JobProfile:
    return JobProfile(
        kind="llm_agent",
        descriptor=str(kwargs["descriptor"]),
        input_size=int(kwargs["input_size"]),
    )


register_operation(_agent_model_request, _inspect_agent_model_request)


def agent_model(max_total_tokens: int, usage: TokenUsage) -> LitellmModel:
    """Return the configured model for an agent run.

    Each call waits for the shared scheduler and adds its tokens to `usage`.
    A call that brings the run above `max_total_tokens` raises
    TokenBudgetExceeded, which ends the run.
    """
    endpoint = llm_endpoint()

    class ScheduledLitellmModel(LitellmModel):
        async def get_response(
            self,
            system_instructions: str | None,
            input: Any,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            get_provider_response = super().get_response
            # Characters of the request; the scheduler estimates its tokens from them.
            input_size = len(system_instructions or "") + len(
                input if isinstance(input, str) else json.dumps(input, default=str)
            )
            response = await scheduler.run(
                _agent_model_request,
                operation_kwargs={
                    "descriptor": endpoint.model,
                    "input_size": input_size,
                    "request": lambda: get_provider_response(
                        system_instructions, input, *args, **kwargs,
                    ),
                },
            )
            usage.requests += 1
            usage.input_tokens += response.usage.input_tokens
            usage.cached_input_tokens += response.usage.input_tokens_details.cached_tokens or 0
            usage.output_tokens += response.usage.output_tokens
            usage.total_tokens += response.usage.total_tokens
            if usage.total_tokens > max_total_tokens:
                raise TokenBudgetExceeded(
                    f"The run used {usage.total_tokens} tokens, more than its "
                    f"limit of {max_total_tokens}."
                )
            return response

    return ScheduledLitellmModel(
        model=endpoint.model, base_url=endpoint.base_url, api_key=endpoint.api_key,
    )

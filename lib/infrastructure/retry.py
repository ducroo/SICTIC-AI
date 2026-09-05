"""Wait-and-retry for provider rate limits (HTTP 429).

A rate-limited call is not a failed attempt: the request never ran, the
provider just asked us to slow down. Callers wrap one logical request in
``with_rate_limit_retry`` so throttling is absorbed by waiting out the
provider's rolling minute instead of burning correction attempts (text
generation) or failing outright (embeddings, which previously had no
retry at all).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

# Three waits spanning ~70-90s in total: enough to clear a per-minute
# quota window even when several processes share it.
RATE_LIMIT_DELAYS_SECONDS: tuple[float, ...] = (10.0, 20.0, 40.0)


async def with_rate_limit_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    is_rate_limit: Callable[[BaseException], bool],
    logger: Any,
    label: str,
    delays: tuple[float, ...] = RATE_LIMIT_DELAYS_SECONDS,
) -> T:
    """Run ``operation``, waiting out rate limits between tries.

    Any error for which ``is_rate_limit`` returns False propagates
    immediately; a rate-limit error propagates only once ``delays`` is
    exhausted. Waits are jittered upward (up to +25%) so concurrent
    callers do not retry in lockstep into the same quota window.
    """
    for delay in (*delays, None):
        try:
            return await operation()
        except Exception as error:
            if delay is None or not is_rate_limit(error):
                raise
            wait = delay * random.uniform(1.0, 1.25)
            logger.warning(
                "%s rate-limited by the provider (429); waiting %.0fs for "
                "the quota window before retrying.",
                label,
                wait,
            )
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover

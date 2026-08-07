from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

import typer

from lib.insights import InsightFile

T = TypeVar("T")


def format_insights(insights: list[InsightFile]) -> str:
    """Render managed insight content and paths at a CLI boundary."""
    return "\n\n".join(
        f"{insight.content()}\n\nRESULT_PATH: {insight.path}"
        for insight in insights
    )


def run_command(
    action: Callable[[], T],
    *,
    logger: Any,
    error_prefix: str | None = None,
) -> T:
    """Run one CLI action with consistent async and error handling."""
    try:
        result = action()
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
    except typer.Exit:
        raise
    except Exception as exc:
        message = f"{error_prefix}: {exc}" if error_prefix else str(exc)
        logger.error(message)
        typer.echo(message, err=True)
        raise typer.Exit(code=1) from exc

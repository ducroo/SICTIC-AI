"""Thin provider-neutral document-conversion interface."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.document_conversion.normalization import (
    normalize_extracted_text,
)
from lib.infrastructure.document_conversion.types import DocumentConversion
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)

Backend = Callable[[Path], DocumentConversion | Awaitable[DocumentConversion]]
DEFAULT_DOCUMENT_CONVERTER = "docling_stack"


async def convert_document(path: str | Path) -> DocumentConversion:
    """Convert one local document into provider-neutral Markdown."""
    source = Path(path)
    if not source.is_file():
        raise InfrastructureError(
            f"Document does not exist or is not a file: {source}",
            kind=InfrastructureErrorKind.DATA_INTEGRITY,
            provider="document_conversion",
            operation="read_input",
        )

    provider = (
        get_env_var("DOCUMENT_CONVERTER", required=False)
        or DEFAULT_DOCUMENT_CONVERTER
    ).strip().lower()
    backend = _backend(provider)
    try:
        if inspect.iscoroutinefunction(backend):
            result = await backend(source)
        else:
            result = await asyncio.to_thread(backend, source)
        markdown = normalize_extracted_text(result.markdown)
    except InfrastructureError:
        raise
    except Exception as error:
        raise _translate_error(provider, source, error) from error
    return DocumentConversion(markdown=markdown, warnings=result.warnings)


def _backend(provider: str) -> Backend:
    if provider == "docling_stack":
        from lib.infrastructure.document_conversion.docling_stack import (
            convert_document as convert_with_docling_stack,
        )

        return convert_with_docling_stack
    raise InfrastructureError(
        f"Unknown document converter {provider!r}",
        kind=InfrastructureErrorKind.CONFIGURATION,
        provider="document_conversion",
        operation="select_provider",
    )


def _translate_error(
    provider: str,
    source: Path,
    error: Exception,
) -> InfrastructureError:
    message = str(error).replace("\n", " ").strip()
    if _is_unsupported_format_error(error):
        return InfrastructureError(
            f"Unsupported document format for {source.name}: {message}",
            kind=InfrastructureErrorKind.INVALID_RESPONSE,
            provider=provider,
            operation="check_format",
        )
    if isinstance(error, TimeoutError) or "timeout" in message.casefold():
        return InfrastructureError(
            f"Timed out converting {source.name}: {message}",
            kind=InfrastructureErrorKind.TIMEOUT,
            provider=provider,
            operation="convert_document",
        )
    return InfrastructureError(
        f"Could not convert {source.name}: {message}",
        kind=InfrastructureErrorKind.INVALID_RESPONSE,
        provider=provider,
        operation="convert_document",
    )


def _is_unsupported_format_error(error: Exception) -> bool:
    text = str(error)
    return (
        "File format not allowed" in text
        or "does not match any allowed format" in text
        or "unsupported document format" in text.casefold()
    )

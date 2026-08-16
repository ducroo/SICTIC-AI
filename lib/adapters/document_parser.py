"""Select the document parser backend used during dataset conversion."""

from __future__ import annotations

import os

from lib.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DOCUMENT_PARSER = "docling"
SUPPORTED_DOCUMENT_PARSERS = frozenset({"docling", "llamaparse"})


def document_parser_backend() -> str:
    raw = (os.environ.get("DOCUMENT_PARSER") or DEFAULT_DOCUMENT_PARSER).strip()
    backend = raw.lower()
    if backend not in SUPPORTED_DOCUMENT_PARSERS:
        raise ValueError(
            f"Unsupported DOCUMENT_PARSER={raw!r}; "
            f"expected one of {sorted(SUPPORTED_DOCUMENT_PARSERS)}"
        )
    return backend


def get_document_parser(*, concurrency_limit: int | None = None):
    """Return an adapter with DoclingAdapter's extract_documents surface."""
    backend = document_parser_backend()
    if backend == "llamaparse":
        from lib.adapters.llamaparse import LlamaParseAdapter

        logger.info("Using LlamaParse SaaS document parser.")
        return LlamaParseAdapter(concurrency_limit=concurrency_limit)

    from lib.adapters.docling import DoclingAdapter

    logger.info("Using Docling document parser.")
    return DoclingAdapter(concurrency_limit=concurrency_limit)

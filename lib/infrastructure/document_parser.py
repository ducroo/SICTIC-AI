"""Select the document parser backend used during dataset conversion."""

from __future__ import annotations

import os

DEFAULT_DOCUMENT_PARSER = "docling"
SAAS_DOCUMENT_PARSER = "llamaparse"  # pragma: allowlist secret
SUPPORTED_DOCUMENT_PARSERS = frozenset(
    {DEFAULT_DOCUMENT_PARSER, SAAS_DOCUMENT_PARSER}
)
SAAS_DOCUMENT_CONVERTER = SAAS_DOCUMENT_PARSER
DEFAULT_DOCUMENT_CONVERTER = "docling_stack"


def document_parser_backend() -> str:
    raw = (os.environ.get("DOCUMENT_PARSER") or "").strip()
    if raw:
        backend = raw.lower()
        if backend not in SUPPORTED_DOCUMENT_PARSERS:
            raise ValueError(
                f"Unsupported DOCUMENT_PARSER={raw!r}; "
                f"expected one of {sorted(SUPPORTED_DOCUMENT_PARSERS)}"
            )
        return backend
    converter = (os.environ.get("DOCUMENT_CONVERTER") or "").strip().lower()
    if converter == SAAS_DOCUMENT_CONVERTER:
        return SAAS_DOCUMENT_PARSER
    return DEFAULT_DOCUMENT_PARSER


def document_converter_provider() -> str:
    """Return the convert_document backend name."""
    parser = document_parser_backend()
    if parser == SAAS_DOCUMENT_PARSER:
        return SAAS_DOCUMENT_CONVERTER
    converter = (os.environ.get("DOCUMENT_CONVERTER") or "").strip().lower()
    return converter or DEFAULT_DOCUMENT_CONVERTER

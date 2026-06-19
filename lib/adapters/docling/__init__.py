"""Document conversion adapter and format-specific helpers."""

from lib.adapters.docling.adapter import DoclingAdapter
from lib.adapters.docling.converter import (
    chat_completions_model as _chat_completions_model,
    chat_completions_url as _chat_completions_url,
)
from lib.adapters.docling.spreadsheets import (
    SPREADSHEET_MARKDOWN_MARKER,
    is_spreadsheet_filename,
)
from lib.adapters.docling.types import (
    ConversionStatus,
    DocumentConversionResult,
)

__all__ = [
    "ConversionStatus",
    "DoclingAdapter",
    "DocumentConversionResult",
    "SPREADSHEET_MARKDOWN_MARKER",
    "_chat_completions_model",
    "_chat_completions_url",
    "is_spreadsheet_filename",
]

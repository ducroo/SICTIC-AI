"""Convert one document at a time through the configured conversion stack."""

from lib.infrastructure.document_conversion.converter import convert_document
from lib.infrastructure.document_conversion.types import (
    DocumentConversion,
    SPREADSHEET_CONVERSION_MARKER,
)

__all__ = [
    "DocumentConversion",
    "SPREADSHEET_CONVERSION_MARKER",
    "convert_document",
]

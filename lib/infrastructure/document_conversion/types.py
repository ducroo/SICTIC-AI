"""Provider-neutral document-conversion results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentConversion:
    """Completed conversion of one source document."""

    markdown: str
    warnings: tuple[str, ...] = ()


SPREADSHEET_CONVERSION_MARKER = (
    "<!-- sictic-document-conversion: spreadsheet-values-v4 -->"
)

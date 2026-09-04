"""Deterministic e-signature evidence from a PDF's raw text layer.

Flattened e-signed PDFs (e.g. DocuSign envelopes re-saved through PDF24)
lose their cryptographic signature objects, but the envelope headers survive
in the raw text layer even when OCR drops them. Scanning for those markers
gives code-side corroboration of an extraction's ``signatures_complete``.
"""

from __future__ import annotations

import re
import zlib

_ENVELOPE_PATTERN = rb"Docusign Envelope ID:?\s*([0-9A-Fa-f-]{16,})"
_PROVIDER_PATTERNS = (
    ("docusign", rb"DocuSign"),
    ("skribble", rb"[Ss]kribble"),
    ("adobe_sign", rb"Adobe\s?Sign"),
)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.S)


def _searchable_chunks(pdf_bytes: bytes) -> list[bytes]:
    """The raw bytes plus every stream that zlib can decompress.

    PDF text content lives in FlateDecode streams, so markers like the
    DocuSign envelope headers are invisible in the raw bytes. Stdlib zlib
    covers the overwhelmingly common case without a PDF dependency.
    """
    chunks = [pdf_bytes]
    for match in _STREAM_RE.finditer(pdf_bytes):
        try:
            chunks.append(zlib.decompress(match.group(1)))
        except zlib.error:
            continue
    return chunks


def _normalize_pdf_text(chunk: bytes) -> bytes:
    """Strip PDF text-operator syntax so split literals still match.

    Text in content streams appears as ``(Docu)Tj (sign)Tj`` fragments;
    removing parentheses and operator noise lets simple substring patterns
    work in the common case.
    """
    return re.sub(rb"[()\\]|\s*Tj\s*|\s*TJ\s*", b"", chunk)


def scan_esign_markers(pdf_bytes: bytes) -> dict[str, list[str]]:
    """Return e-signature markers found anywhere in a PDF's content."""
    markers: dict[str, list[str]] = {}
    envelope_ids: set[str] = set()
    providers: set[str] = set()
    for raw_chunk in _searchable_chunks(pdf_bytes):
        for chunk in (raw_chunk, _normalize_pdf_text(raw_chunk)):
            for match in re.finditer(_ENVELOPE_PATTERN, chunk, re.I):
                envelope_ids.add(match.group(1).decode("ascii", "replace"))
            for name, pattern in _PROVIDER_PATTERNS:
                if re.search(pattern, chunk):
                    providers.add(name)
    if envelope_ids:
        markers["docusign_envelope_ids"] = sorted(envelope_ids)
    if providers:
        markers["providers"] = sorted(providers)
    return markers

"""Repairs and filtering for extracted document text."""

from __future__ import annotations

import unicodedata


_PRIVATE_USE_DENSITY_THRESHOLD = 0.1
_PRESERVED_CONTROLS = {"\t", "\n", "\r"}


def has_dense_private_use_encoding(text: str) -> bool:
    """Return whether private-use glyphs indicate encoded body text."""
    if not text:
        return False
    private_use_count = sum(_is_private_use(ord(char)) for char in text)
    return private_use_count / len(text) >= _PRIVATE_USE_DENSITY_THRESHOLD


def requires_text_normalization(text: str) -> bool:
    """Return whether persisted extracted text contains excluded code points."""
    return any(_is_excluded(ord(char)) for char in text)


def normalize_extracted_text(text: str) -> str:
    """Normalize text and replace unsafe code points with spaces."""
    text = unicodedata.normalize("NFC", text)
    if has_dense_private_use_encoding(text):
        raise ValueError(
            "High-density private-use character encoding requires OCR."
        )

    cleaned: list[str] = []
    replacing = False
    for char in text:
        if _is_excluded(ord(char)):
            if not replacing:
                cleaned.append(" ")
            replacing = True
            continue
        cleaned.append(char)
        replacing = False
    return "".join(cleaned)


def _is_private_use(codepoint: int) -> bool:
    return (
        0xE000 <= codepoint <= 0xF8FF
        or 0xF0000 <= codepoint <= 0xFFFFD
        or 0x100000 <= codepoint <= 0x10FFFD
    )


def _is_excluded(codepoint: int) -> bool:
    char = chr(codepoint)
    if char in _PRESERVED_CONTROLS:
        return False
    if (
        0x0000 <= codepoint <= 0x001F
        or 0x007F <= codepoint <= 0x009F
        or 0xD800 <= codepoint <= 0xDFFF
        or _is_private_use(codepoint)
        or 0xFDD0 <= codepoint <= 0xFDEF
    ):
        return True
    return codepoint & 0xFFFF in {0xFFFE, 0xFFFF}

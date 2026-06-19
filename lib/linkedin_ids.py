from __future__ import annotations

import unicodedata


def normalize_linkedin_id(value: str) -> str:
    return unicodedata.normalize("NFC", (value or "").strip().strip("/").lower())

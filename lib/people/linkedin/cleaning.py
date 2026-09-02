"""Create the stored, searchable representation of a LinkedIn profile."""

from __future__ import annotations

import re

_NETWORK_FIELDS = {
    "peoplealsoviewed",
    "similarprofiles",
    "recommendations",
}
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)]\(https?://[^)]+\)", re.IGNORECASE)
_WEB_LINK = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)


def clean_linkedin_payload(payload: dict) -> dict:
    """Remove low-signal technical and linked content without mutating input."""

    def clean_node(node):
        if isinstance(node, dict):
            cleaned = {}
            for key, value in node.items():
                lowered = key.casefold()
                if lowered in _NETWORK_FIELDS:
                    continue
                if (
                    "image" in lowered
                    or "urn" in lowered
                    or lowered.startswith("multilocale")
                ):
                    continue
                cleaned_value = clean_node(value)
                if cleaned_value not in (None, "", [], {}):
                    cleaned[key] = cleaned_value
            return cleaned
        if isinstance(node, list):
            return [
                cleaned
                for item in node
                if (cleaned := clean_node(item)) not in (None, "", [], {})
            ]
        if isinstance(node, str):
            if node.strip().casefold().startswith("urn:"):
                return ""
            without_markdown_targets = _MARKDOWN_LINK.sub(r"\1", node)
            without_links = _WEB_LINK.sub("", without_markdown_targets)
            return " ".join(without_links.split())
        return node

    return clean_node(payload)

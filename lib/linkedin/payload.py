from __future__ import annotations


_NETWORK_FIELDS = {
    "peopleAlsoViewed",
    "similarProfiles",
    "recommendations",
}


def clean_linkedin_payload(data: dict) -> dict:
    """Remove low-signal graph/media fields while preserving profile content."""

    def clean_node(node):
        if isinstance(node, dict):
            cleaned = {}
            for key, value in node.items():
                lowered = key.lower()
                if key in _NETWORK_FIELDS:
                    continue
                if (
                    "image" in lowered
                    or "urn" in lowered
                    or key.startswith("multiLocale")
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
        return node

    return clean_node(data)

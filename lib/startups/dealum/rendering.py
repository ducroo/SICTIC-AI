from __future__ import annotations

import json
from typing import Any

from lib.startups.dealum.manifest import replace_attachment_urls


def render_application_markdown(
    application: dict[str, Any],
    *,
    dealum_url: str | None = None,
    attachment_replacements: dict[str, str] | None = None,
) -> str:
    name = application.get("name") or "Unknown startup"
    lines = [f"# Dealum Application: {name}", ""]
    lines.extend(
        [
            f"- Dealum ID: {application.get('id', '')}",
            f"- Dealum URL: {dealum_url or ''}",
            f"- Code: {application.get('code', '')}",
            f"- Tags: {', '.join(sorted(application.get('tags') or []))}",
            "",
        ]
    )

    contact = application.get("contact") or {}
    if any(
        contact.get(key)
        for key in ("firstName", "lastName", "email", "phone")
    ):
        lines.extend(["## Contact", ""])
        full_name = " ".join(
            part
            for part in (
                contact.get("firstName"),
                contact.get("lastName"),
            )
            if part
        )
        if full_name:
            lines.append(f"- Name: {full_name}")
        for key, label in (("email", "Email"), ("phone", "Phone")):
            if contact.get(key):
                lines.append(f"- {label}: {contact[key]}")
        lines.append("")

    answers = replace_attachment_urls(
        application.get("answers") or {},
        attachment_replacements or {},
    )
    if isinstance(answers, dict):
        lines.extend(["## Application Answers", ""])
        for key in sorted(answers):
            lines.extend(
                [
                    f"### {key}",
                    "",
                    _markdown_value(answers[key]),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _markdown_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(
            (
                f"- `{json.dumps(item, ensure_ascii=False, sort_keys=True)}`"
                if isinstance(item, (dict, list))
                else f"- {item}"
            )
            for item in value
        )
    if isinstance(value, dict):
        return (
            "```json\n"
            + json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n```"
        )
    return str(value)

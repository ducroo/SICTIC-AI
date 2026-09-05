"""Convert person-oriented Markdown tables into domain objects."""

from __future__ import annotations

import re
from typing import Any

from lib.markdown_tables import is_separator_row, is_table_line, split_cells
from lib.people.linkedin import extract_linkedin_id
from lib.people.model import Person, normalize_email_addresses


_IDENTITY_COLUMNS = {
    "full_name": {"full_name", "fullname", "name", "investor_name", "expert_name"},
    "email_addresses": {"email", "email_address", "email_addresses", "emailaddresses"},
    "linkedin_id": {
        "linkedin",
        "linkedin_id",
        "linkedinid",
        "linkedin_profile",
        "linkedin_url",
    },
}


def _column_name(value: str) -> str:
    # Preserve internal underscores in standard identity column names. Strip
    # only surrounding emphasis, and unescape separators used by roster files.
    value = value.strip().strip("*_`").replace(r"\_", "_").replace(r"\-", "-").lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _cell(value: str) -> str:
    return value.replace(r"\|", "|").strip()


def _markdown_link_target(value: str) -> str:
    match = re.fullmatch(r"\s*\[[^]]*]\(([^)]+)\)\s*", value)
    return match.group(1) if match else value


def _identity_key(column: str) -> str | None:
    return next(
        (key for key, aliases in _IDENTITY_COLUMNS.items() if column in aliases),
        None,
    )


def _table_groups(markdown: str) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if is_table_line(line):
            current.append(line.strip())
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def markdown_table_to_person_objects(
    markdown: str,
    *,
    tag: str,
) -> list[Person]:
    """Parse the first person-oriented Markdown table, preserving row order.

    Identity columns populate :class:`Person`; every other column is retained
    under ``person.adhoc_data[tag]``.
    """
    if not tag.strip():
        raise ValueError("tag must not be empty")

    for rows in _table_groups(markdown):
        if len(rows) < 2:
            continue
        headers = [_column_name(cell) for cell in split_cells(rows[0])]
        identity_columns = [_identity_key(header) for header in headers]
        if not any(identity_columns):
            continue

        body = rows[1:]
        if body and is_separator_row(body[0]):
            body = body[1:]

        people: list[Person] = []
        for row in body:
            if is_separator_row(row):
                continue
            values = [_cell(value) for value in split_cells(row)]
            values.extend([""] * (len(headers) - len(values)))
            identity: dict[str, Any] = {
                "full_name": "",
                "email_addresses": [],
                "linkedin_id": "",
            }
            adhoc_values: dict[str, Any] = {}
            for header, identity_key, value in zip(headers, identity_columns, values):
                if identity_key == "full_name":
                    identity[identity_key] = value
                elif identity_key == "email_addresses":
                    identity[identity_key] = normalize_email_addresses(value)
                elif identity_key == "linkedin_id":
                    identity[identity_key] = extract_linkedin_id(
                        _markdown_link_target(value)
                    )
                elif header:
                    adhoc_values[header] = value

            person = Person(**identity)
            if not person.identifier:
                continue
            person.adhoc_data[tag] = adhoc_values
            people.append(person)

        return people

    raise ValueError("No person-oriented Markdown table was found")

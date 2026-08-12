"""Structured response schema specialization and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from lib.json_parser import repair_json_payload
from lib.slugify import slugify


@dataclass(frozen=True)
class Suggestion:
    startup_name: str
    rank: int
    rationale: str


def specialize_schema(
    response_schema: dict[str, Any],
    candidate_startups: list[str],
    max_startups: int,
) -> dict[str, Any]:
    specialized = deepcopy(response_schema)
    try:
        suggestions = specialized["properties"]["suggestions"]
        properties = suggestions["items"]["properties"]
        startup_name = properties["startup_name"]
        rank = properties["rank"]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "Suggested-startups response schema must define "
            "suggestions[].startup_name and suggestions[].rank."
        ) from error
    suggestions["maxItems"] = max_startups
    startup_name["enum"] = candidate_startups
    rank["maximum"] = max_startups
    return specialized


def response_format(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "suggested_startups_response",
            "strict": True,
            "schema": schema,
        },
    }


def parse_suggestions(
    raw_response: str,
    schema: dict[str, Any],
    candidate_startups: list[str],
    max_startups: int,
) -> list[Suggestion]:
    parsed = repair_json_payload(raw_response)
    _validate_schema(parsed, schema)
    return _validate_business_rules(
        parsed["suggestions"],
        candidate_startups,
        max_startups,
    )


def _validation_path(error: ValidationError) -> str:
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _validate_schema(parsed: object, schema: dict[str, Any]) -> None:
    try:
        validator = Draft202012Validator(schema)
        validator.check_schema(schema)
        validator.validate(parsed)
    except SchemaError as error:
        raise ValueError(
            f"Invalid suggested-startups response schema: {error}"
        ) from error
    except ValidationError as error:
        raise ValueError(
            "Suggested-startups response does not match the schema at "
            f"{_validation_path(error)}: {error.message}"
        ) from error


def _validate_business_rules(
    suggestions: list[dict[str, Any]],
    candidate_startups: list[str],
    max_startups: int,
) -> list[Suggestion]:
    if len(suggestions) > max_startups:
        raise ValueError(
            f"Suggested-startups response contains {len(suggestions)} "
            f"results; maximum is {max_startups}."
        )
    candidates = {slugify(name): name for name in candidate_startups}
    if len(candidates) != len(candidate_startups):
        raise ValueError("Candidate startup names are not unique.")

    normalized: list[Suggestion] = []
    seen: set[str] = set()
    ranks: list[int] = []
    for item in suggestions:
        supplied_name = item["startup_name"].strip()
        startup_slug = slugify(supplied_name)
        if startup_slug not in candidates:
            raise ValueError(
                f"Unknown suggested startup {supplied_name!r}; expected one "
                f"of {candidate_startups}."
            )
        if startup_slug in seen:
            raise ValueError(f"Duplicate suggested startup {supplied_name!r}.")
        rationale = item["rationale"].strip()
        if not rationale:
            raise ValueError(
                f"Suggested startup {supplied_name!r} has an empty rationale."
            )
        seen.add(startup_slug)
        ranks.append(item["rank"])
        normalized.append(
            Suggestion(candidates[startup_slug], item["rank"], rationale)
        )

    if sorted(ranks) != list(range(1, len(normalized) + 1)):
        raise ValueError(
            "Suggested-startups ranks must be unique and sequential from 1; "
            f"received {ranks}."
        )
    return sorted(normalized, key=lambda item: item.rank)

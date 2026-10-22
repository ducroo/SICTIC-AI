"""Provider schemas, deterministic consistency review and derived categories."""

from __future__ import annotations

from copy import deepcopy

from lib.infrastructure.ai_text_generation import Review
from lib.infrastructure.ai_text_generation.json import copy_schema


def response_schema(reference: dict, template: dict) -> dict:
    """Use the same category IDs and limits for the prompt and validation."""
    schema = copy_schema(template)
    components = schema["properties"]["classifications"]
    constraints = []
    for name, component in reference["components"].items():
        ids = [category["id"] for category in component["categories"]]
        components["properties"][name] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "primary": {"type": ["string", "null"], "enum": [*ids, None]},
                "secondary": {
                    "type": "array", "items": {"type": "string", "enum": ids},
                    "uniqueItems": True, "maxItems": component["max_secondary"],
                },
            },
            "required": ["primary", "secondary"],
            "allOf": [{
                "if": {"properties": {"primary": {"const": None}}},
                "then": {"properties": {"secondary": {"maxItems": 0}}},
            }],
        }
        constraints.append({
            "if": {"properties": {"classifications": {"properties": {
                name: {"properties": {"primary": {"type": "string"}}},
            }}}},
            "then": {"properties": {"evidence": {"minItems": 1}}},
        })
    components["required"] = list(reference["components"])
    constraints.append({
        "if": {"properties": {"classifications": {"properties": {
            "industries": {"properties": {"primary": {"const": None}}},
        }}}},
        "then": {"properties": {"confidence": {"const": "L"}}},
    })
    schema["allOf"] = constraints
    return schema


def selected(selection: dict) -> list[str]:
    return ([selection["primary"]] if selection["primary"] else []) + selection["secondary"]


def review_classification(result: dict, reference: dict) -> Review:
    """Only semantic relationships left after shared JSON schema validation."""
    problems = []
    choices = result["classifications"]
    for name, selection in choices.items():
        if selection["primary"] in selection["secondary"]:
            problems.append(f"{name}: primary must not also be secondary.")
        component = reference["components"][name]
        parent_name = component.get("parent_component")
        if parent_name not in choices:
            continue  # PitchBook parents are derived, not independently selected.
        parents = choices[parent_name]
        categories = {c["id"]: c for c in component["categories"]}
        for ident in selected(selection):
            allowed = categories[ident]["parents"]
            if not set(allowed).intersection(selected(parents)):
                problems.append(f"{name}/{ident} needs a selected parent in {allowed}.")
        if selection["primary"]:
            allowed = categories[selection["primary"]]["parents"]
            if parents["primary"] not in allowed:
                problems.append(f"Primary {name} must belong to primary {parent_name}.")
    return Review(result, tuple(problems))


def derive(result: dict, reference: dict) -> dict:
    """Derive ancestor paths and the reporting rules verified in the reference."""
    components = {**reference["components"], **reference["derived_components"]}
    selections = {key: selected(value) for key, value in result["classifications"].items()}
    ancestors: dict[str, list[str]] = {}

    def add_parents(name: str, identifiers: list[str]) -> None:
        component = components[name]
        parent = component.get("parent_component")
        if parent not in reference["derived_components"]:
            return
        categories = {c["id"]: c for c in component["categories"]}
        values = ancestors.setdefault(parent, [])
        for ident in identifiers:
            for parent_id in categories[ident]["parents"]:
                if parent_id not in values:
                    values.append(parent_id)
                    add_parents(parent, [parent_id])

    for name, values in selections.items():
        add_parents(name, values)
    matched, unevaluated = [], []
    for group in reference["reporting_groups"]:
        rule = group["rule"]
        if rule is None:
            unevaluated.append(group["id"])
            continue
        required = {term["component"] for term in [*rule["any"], *rule["exclude"]]}
        if any(not selections.get(name) for name in required):
            # An unknown component is not evidence of absence.
            unevaluated.append(group["id"])
            continue

        def matches(term: dict) -> bool:
            return term["id"] in selections[term["component"]]

        if any(map(matches, rule["any"])) and not any(map(matches, rule["exclude"])):
            matched.append(group["id"])
    return {"parents": ancestors, "reporting_groups": matched,
            "unevaluated_reporting_groups": unevaluated}


def provider_record(result: dict, reference: dict) -> dict:
    """Attach provenance and resolve selected display names without a model."""
    derived = derive(result, reference)
    names = {}
    for name, component in {**reference["components"], **reference["derived_components"]}.items():
        ids = (selected(result["classifications"][name])
               if name in result["classifications"] else derived["parents"].get(name, []))
        lookup = {c["id"]: c["name"] for c in component["categories"]}
        names[name] = {ident: lookup[ident] for ident in ids}
    return {
        "taxonomy": {key: deepcopy(reference[key]) for key in ("provider", "version", "status", "sources")},
        "result": result,
        "category_names": names,
        "derived": derived,
    }

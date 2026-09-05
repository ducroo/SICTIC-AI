"""Team-editable CLA term checklist → extraction schema + prompt block.

``config/captable/cla_terms.md`` is the single source of truth for WHAT
the CLA extraction looks for — the same pattern as
``config/dd_checks/checklists/`` driving dd_checks: the team adds terms
or refines guidance by editing config, no code change. Each
``### field (type)`` entry becomes one schema field; its body becomes
the model guidance for that term. ``structural`` fields take their
shape from ``cla_extraction_base_schema.json`` (the code owns those
shapes).

The pipeline COMPUTES on some fields (aggregation, assessment,
analysis, validation read them by name). Removing or re-typing one of
those in the markdown would not crash anything — values would silently
read as None and, e.g., outstanding principal would report 0. That
failure mode is unacceptable, so ``CODE_CONSUMED_FIELDS`` fails loudly
at load time instead. Adding terms is always safe: extraction, quote
verification, and missing_terms handle unknown fields generically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SIMPLE_KINDS = {
    "number": "quoted_number",
    "string": "quoted_string",
    "boolean": "quoted_boolean",
    "presence boolean": "quoted_boolean",
}
_KINDS = set(_SIMPLE_KINDS) | {"enum", "enum list", "structural"}

_HEADING = re.compile(r"^### ([a-z][a-z0-9_]*) \(([^)]+)\)\s*$")

# field -> (kind, required enum members) for every field the pipeline
# reads by name. The empty tuple means "any members".
CODE_CONSUMED_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "lenders": ("structural", ()),
    "status": ("structural", ()),
    "missing_terms": ("structural", ()),
    "execution_date": ("string", ()),
    "signatures_complete": ("boolean", ()),
    "principal_total": ("number", ()),
    "principal_currency": ("string", ()),
    "interest_mode": ("enum", ("safe_harbor_capped", "unstated")),
    "interest_rate_pct": ("number", ()),
    "interest_safe_harbor_rate_pct": ("number", ()),
    "interest_day_count": ("enum", ("unstated",)),
    "interest_compounding": ("enum", ("simple", "unstated")),
    "maturity_date": ("string", ()),
    "qefr_present": ("presence boolean", ()),
    "qefr_min_raise": ("number", ()),
    "qefr_min_new_money": ("number", ()),
    "coc_present": ("presence boolean", ()),
    "coc_repayment_multiple": ("number", ()),
    "maturity_conversion_present": ("presence boolean", ()),
    "maturity_conversion_price": ("number", ()),
    "valuation_cap": ("number", ()),
    "discount_pct": ("number", ()),
    "valuation_floor": ("number", ()),
    "denominator_basis": ("enum", ("unstated",)),
    "subordinated": ("boolean", ()),
    "subordination_scope": (
        "enum",
        ("loan_balance_full", "principal_only", "not_subordinated"),
    ),
    "mfn_clause": ("presence boolean", ()),
    "pro_rata_rights": ("presence boolean", ()),
    "conversion_capital_sources": ("enum list", ()),
    "shareholder_consents_referenced": ("boolean", ()),
    "sha_accession_required": ("boolean", ()),
}


@dataclass(frozen=True)
class Term:
    name: str
    kind: str
    members: tuple[str, ...]
    group: str
    guidance: str


def parse_cla_terms(markdown: str) -> list[Term]:
    """Parse the checklist; every grammar violation names its heading."""
    terms: list[Term] = []
    group = ""
    name = kind = None
    members: tuple[str, ...] = ()
    body: list[str] = []

    def flush() -> None:
        nonlocal name
        if name is None:
            return
        guidance = " ".join(
            line.strip() for line in body if line.strip()
        )
        if not guidance:
            raise ValueError(f"cla_terms.md: `{name}` has no guidance text.")
        terms.append(Term(name, kind, members, group, guidance))
        name = None

    for line in markdown.splitlines():
        if line.startswith("### "):
            flush()
            match = _HEADING.match(line)
            if not match:
                raise ValueError(
                    "cla_terms.md: malformed term heading "
                    f"{line!r} — expected `### field_name (type)`."
                )
            name, spec = match.group(1), match.group(2).strip()
            if any(term.name == name for term in terms):
                raise ValueError(f"cla_terms.md: duplicate term `{name}`.")
            if ":" in spec:
                kind, raw = (part.strip() for part in spec.split(":", 1))
                members = tuple(
                    member.strip()
                    for member in raw.split("|")
                    if member.strip()
                )
            else:
                kind, members = spec, ()
            if kind not in _KINDS:
                raise ValueError(
                    f"cla_terms.md: `{name}` has unknown type {kind!r} "
                    f"(known: {sorted(_KINDS)})."
                )
            if kind.startswith("enum") and not members:
                raise ValueError(
                    f"cla_terms.md: `{name}` is an enum without members."
                )
            body = []
        elif line.startswith("## "):
            flush()
            group = line[3:].strip()
        elif line.startswith("# "):
            flush()
        elif name is not None:
            body.append(line)
    flush()
    if not terms:
        raise ValueError("cla_terms.md: no terms found.")
    _guard_code_consumed(terms)
    return terms


def _guard_code_consumed(terms: list[Term]) -> None:
    by_name = {term.name: term for term in terms}
    for field, (kind, required_members) in CODE_CONSUMED_FIELDS.items():
        term = by_name.get(field)
        if term is None:
            raise ValueError(
                f"cla_terms.md: `{field}` is missing, but the pipeline "
                "computes on it (see CODE_CONSUMED_FIELDS in "
                "lib/captable/cla_terms.py). Removing it would silently "
                "zero out downstream numbers — restore the term."
            )
        if term.kind != kind:
            raise ValueError(
                f"cla_terms.md: `{field}` must stay of type {kind!r} "
                f"(found {term.kind!r}) — the pipeline computes on it."
            )
        missing = [m for m in required_members if m not in term.members]
        if missing:
            raise ValueError(
                f"cla_terms.md: `{field}` must keep enum member(s) "
                f"{missing} — code compares against them."
            )


def _enum_property(term: Term) -> dict[str, Any]:
    value: dict[str, Any] = (
        {
            "type": "array",
            "items": {"type": "string", "enum": list(term.members)},
        }
        if term.kind == "enum list"
        else {"type": "string", "enum": list(term.members)}
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "quote"],
        "properties": {"value": value, "quote": {"type": ["string", "null"]}},
    }


def build_cla_schema(config: dict[str, Any]) -> dict[str, Any]:
    """Assemble schema + reviewer inputs + prompt block from config.

    Returns ``{"schema", "quoted_fields", "presence_fields",
    "prompt_block"}``. Property order follows the markdown exactly (the
    model generates in that order).
    """
    terms = parse_cla_terms(config["cla_terms"])
    base = config["cla_extraction_base_schema"]
    properties: dict[str, Any] = {}
    for term in terms:
        if term.kind == "structural":
            shape = base["properties"].get(term.name)
            if shape is None:
                raise ValueError(
                    f"cla_terms.md: `{term.name}` is structural but "
                    "cla_extraction_base_schema.json has no shape for it."
                )
            properties[term.name] = shape
        elif term.kind in _SIMPLE_KINDS:
            properties[term.name] = {
                "$ref": f"#/$defs/{_SIMPLE_KINDS[term.kind]}"
            }
        else:
            properties[term.name] = _enum_property(term)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [term.name for term in terms],
        "properties": properties,
        "$defs": base["$defs"],
    }
    quoted_fields = tuple(
        term.name for term in terms if term.kind != "structural"
    )
    presence_fields = frozenset(
        term.name for term in terms if term.kind == "presence boolean"
    )
    return {
        "schema": schema,
        "quoted_fields": quoted_fields,
        "presence_fields": presence_fields,
        "prompt_block": _render_prompt_block(terms),
    }


def _render_prompt_block(terms: list[Term]) -> str:
    lines = ["### TERMS TO EXTRACT", ""]
    group = None
    for term in terms:
        if term.group != group:
            group = term.group
            lines += [f"#### {group}", ""]
        spec = term.kind + (
            f": {' | '.join(term.members)}" if term.members else ""
        )
        lines.append(f"- `{term.name}` ({spec}): {term.guidance}")
    return "\n".join(lines)

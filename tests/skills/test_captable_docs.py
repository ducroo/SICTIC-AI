"""Pin the docs' term inventory to the config schemas (no drift)."""

from __future__ import annotations

import json
import re
from pathlib import Path

DESIGN_DOC = Path("docs/captable-design.md").read_text(encoding="utf-8")


def test_every_cla_schema_field_is_documented() -> None:
    """docs/captable-design.md promises a complete term inventory —
    adding a schema field without documenting it must fail here."""
    schema = json.loads(
        Path(
            "config/captable/cla_extraction_response_schema.json"
        ).read_text(encoding="utf-8")
    )
    missing = [
        field
        for field in schema["properties"]
        if f"`{field}`" not in DESIGN_DOC
    ]
    assert not missing, (
        "CLA schema fields missing from docs/captable-design.md's term "
        f"inventory: {missing}"
    )


def test_every_assessment_rule_key_is_reflected() -> None:
    rules = json.loads(
        Path("config/captable/assessment_rules.json").read_text(
            encoding="utf-8"
        )
    )
    # The doc names the file as the home of the bands; every configured
    # band must correspond to a documented assessment concern.
    assert "assessment_rules.json" in DESIGN_DOC
    for key in rules:
        prefix = key.split("_")[0]
        assert prefix in DESIGN_DOC, (
            f"assessment_rules.json key {key!r} has no trace in the "
            "design doc"
        )


def test_every_assessment_item_is_documented() -> None:
    source = Path("lib/captable/assessment.py").read_text(
        encoding="utf-8"
    )
    items = set(
        re.findall(r'_finding\(\s*\n?\s*"([a-z_]+)"', source)
    )
    assert items, "no assessment items found — regex out of date?"
    missing = [
        item for item in sorted(items) if f"`{item}`" not in DESIGN_DOC
    ]
    assert not missing, (
        "assessment items missing from docs/captable-design.md: "
        f"{missing}"
    )

"""Pin the docs' term inventory to the config schemas (no drift)."""

from __future__ import annotations

import json
import re
from pathlib import Path

DESIGN_DOC = Path("docs/captable-design.md").read_text(encoding="utf-8")


def test_every_code_consumed_field_is_documented() -> None:
    """The full term list is team-editable config
    (config/captable/cla_terms.md — the checklist itself); the design
    doc documents the code-consumed core, which must stay complete."""
    from lib.captable.cla_terms import CODE_CONSUMED_FIELDS

    assert "cla_terms.md" in DESIGN_DOC
    missing = [
        field
        for field in CODE_CONSUMED_FIELDS
        if f"`{field}`" not in DESIGN_DOC
    ]
    assert not missing, (
        "code-consumed CLA fields missing from docs/captable-design.md: "
        f"{missing}"
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

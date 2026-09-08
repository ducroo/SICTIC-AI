"""Tests for the team-editable CLA term checklist parser/generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.captable.cla_terms import (
    CODE_CONSUMED_FIELDS,
    build_cla_schema,
    parse_cla_terms,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "captable"


def _config() -> dict:
    return {
        "cla_terms": (CONFIG_DIR / "cla_terms.md").read_text(
            encoding="utf-8"
        ),
        "cla_extraction_base_schema": json.loads(
            (CONFIG_DIR / "cla_extraction_base_schema.json").read_text(
                encoding="utf-8"
            )
        ),
    }


def _minimal_md() -> str:
    """The smallest checklist satisfying the code-consumed guard."""
    lines = ["# t", "", "## g", ""]
    kinds = {
        "interest_mode": "enum: safe_harbor_capped | unstated",
        "interest_day_count": "enum: unstated",
        "interest_compounding": "enum: simple | unstated",
        "denominator_basis": "enum: unstated",
        "subordination_scope": (
            "enum: loan_balance_full | principal_only | not_subordinated"
        ),
        "conversion_capital_sources": "enum list: consents",
    }
    for field, (kind, _members) in CODE_CONSUMED_FIELDS.items():
        lines += [f"### {field} ({kinds.get(field, kind)})", "", "Guidance.", ""]
    return "\n".join(lines)


def test_real_checklist_builds_the_expected_schema() -> None:
    built = build_cla_schema(_config())
    schema = built["schema"]
    assert len(schema["properties"]) == 38
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    # structural shapes come from the base file, verbatim
    base = _config()["cla_extraction_base_schema"]
    for name in ("lenders", "status", "status_evidence", "missing_terms"):
        assert schema["properties"][name] == base["properties"][name]
    # every non-structural field is quote-reviewed; presence set is exact
    assert len(built["quoted_fields"]) == 34
    assert built["presence_fields"] == {
        "qefr_present",
        "coc_present",
        "maturity_conversion_present",
        "mfn_clause",
        "pro_rata_rights",
    }
    assert "TERMS TO EXTRACT" in built["prompt_block"]
    assert "`maturity_conversion_price`" in built["prompt_block"]


def test_adding_a_team_term_needs_no_code_change() -> None:
    config = _config()
    config["cla_terms"] += (
        "\n### founder_lockup_months (number)\n\n"
        "Any lock-up period binding the founders, in months.\n"
    )
    built = build_cla_schema(config)
    assert built["schema"]["properties"]["founder_lockup_months"] == {
        "$ref": "#/$defs/quoted_number"
    }
    assert "founder_lockup_months" in built["quoted_fields"]
    assert "founder_lockup_months" in built["schema"]["required"]


def test_removing_a_code_consumed_field_fails_loudly() -> None:
    md = _minimal_md().replace("### principal_total (number)", "### x (number)")
    with pytest.raises(ValueError, match="principal_total"):
        parse_cla_terms(md)


def test_retyping_a_code_consumed_field_fails_loudly() -> None:
    md = _minimal_md().replace(
        "### principal_total (number)", "### principal_total (string)"
    )
    with pytest.raises(ValueError, match="must stay of type"):
        parse_cla_terms(md)


def test_dropping_a_required_enum_member_fails_loudly() -> None:
    md = _minimal_md().replace(
        "### interest_mode (enum: safe_harbor_capped | unstated)",
        "### interest_mode (enum: fixed | unstated)",
    )
    with pytest.raises(ValueError, match="safe_harbor_capped"):
        parse_cla_terms(md)


def test_grammar_errors_name_the_term() -> None:
    with pytest.raises(ValueError, match="unknown type"):
        parse_cla_terms("### foo (blob)\n\nText.\n" + _minimal_md())
    with pytest.raises(ValueError, match="duplicate"):
        parse_cla_terms(
            _minimal_md()
            + "\n### principal_total (number)\n\nAgain.\n"
        )
    with pytest.raises(ValueError, match="malformed term heading"):
        parse_cla_terms("### Bad Heading\n\nText.\n")
    with pytest.raises(ValueError, match="no guidance"):
        parse_cla_terms(_minimal_md() + "\n### empty_term (number)\n")


def test_unknown_structural_field_fails() -> None:
    config = _config()
    config["cla_terms"] += "\n### mystery (structural)\n\nText.\n"
    with pytest.raises(ValueError, match="mystery"):
        build_cla_schema(config)

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

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "captable_build"


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
        "documentation_form": "enum: seca_short_form | seca_long_form | bespoke | unstated",
    }
    for field, (kind, _members) in CODE_CONSUMED_FIELDS.items():
        lines += [f"### {field} ({kinds.get(field, kind)})", "", "Guidance.", ""]
    return "\n".join(lines)


def test_real_checklist_builds_the_expected_schema() -> None:
    built = build_cla_schema(_config())
    schema = built["schema"]
    assert len(schema["properties"]) == 55
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    # structural shapes come from the base file, verbatim
    base = _config()["cla_extraction_base_schema"]
    for name in ("lenders", "status", "status_evidence", "missing_terms", "comments"):
        assert schema["properties"][name] == base["properties"][name]
    # every non-structural field is quote-reviewed; presence set is exact
    assert len(built["quoted_fields"]) == 50
    assert built["presence_fields"] == {
        "qefr_present",
        "coc_present",
        "maturity_conversion_present",
        "mfn_clause",
        "pro_rata_rights",
        "non_qualified_voluntary_conversion",
        "conditions_precedent",
        "representations_and_covenants",
        "exclusivity_present",
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


# --- term-sheet provisions (cla_review, design decision 1): no legacy schema ---

def test_stored_extraction_without_a_term_sheet_field_is_invalid(mock_env) -> None:
    from lib.captable.schema import validate_build_artifact
    from tests.skills.test_captable_build import _complete_cla

    cla = _complete_cla()
    validate_build_artifact({"dataset": "fixture", "clas": [cla], "failures": []}, "loan-extraction")
    del cla["exclusivity_present"]
    with pytest.raises(ValueError, match="exclusivity_present"):
        validate_build_artifact({"dataset": "fixture", "clas": [cla], "failures": []}, "loan-extraction")


def test_loan_extraction_key_follows_the_checklist(mock_env, monkeypatch) -> None:
    from lib.captable import insights
    from lib.datasets.paths import dataset_location_for_domain
    from lib.insights import InsightFile
    from lib.storage import get_storage

    location = dataset_location_for_domain("fixture", "startups")
    for path in (location.raw_rel, location.parsed_rel, location.insights_rel):
        get_storage().mkdir(path)
    classification = InsightFile(
        "fixture", "captable_build", "test-model-1b",
        identifier="classification", subdir=True, extension="json",
    )
    classification.save('{"dataset": "fixture", "documents": []}')
    before = insights.configured_build_insight("fixture", "loan-extraction", classification).config_key

    real = insights.load_repository_config

    def with_extra_term(*sections):
        config = dict(real(*sections))
        config["cla_terms"] += "\n### founder_lockup_months (number)\n\nGuidance.\n"
        return config

    monkeypatch.setattr(insights, "load_repository_config", with_extra_term)
    after = insights.configured_build_insight("fixture", "loan-extraction", classification).config_key
    assert before != after

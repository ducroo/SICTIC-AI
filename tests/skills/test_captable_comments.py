"""Verbatim CLA comments are retained for human review, outside calculations."""
import json
from copy import deepcopy
from datetime import date

import pytest
from jsonschema import validate, ValidationError

from lib.captable.cla_terms import build_cla_schema
from lib.captable.data import assemble_result
from lib.captable.insights import build_insight, read_build_insight
from lib.captable.render_markdown import render_report
from lib.infrastructure.configuration import load_repository_config
from skills.captable.captable import build_scenarios
from tests.skills.test_captable_build import _minimal_extraction, _reviewer, DOC_TEXT, _install_dataset
from tests.skills.test_captable_render import _snapshot, _computed

QUOTE = 'Tenity shall hold 2.5% post-money.\nThe basis is A | B < C & D.'


def test_comment_schema_is_nullable_string_without_quote_review():
    built = build_cla_schema(load_repository_config("captable_build"))
    schema = built["schema"]["properties"]["comments"]
    assert "comments" in built["schema"]["required"]
    for value in (None, QUOTE):
        validate(value, schema)
    with pytest.raises(ValidationError):
        validate({"comment": QUOTE, "quote": QUOTE}, schema)
    assert "comments" not in built["quoted_fields"]
    # Intentionally not in DOC_TEXT: human review, no new source check.
    assert not _reviewer(DOC_TEXT)(_minimal_extraction(comments=QUOTE)).problems
    output = _minimal_extraction()
    output["comments"] = None
    assert not _reviewer(DOC_TEXT)(output).problems


def test_consolidation_and_insight_storage_preserve_comments(mock_env):
    _install_dataset("comments-co", "Cap table")
    loan = {"document": "loan.md", "comments": QUOTE}
    result = assemble_result("comments-co", classification={"documents": []},
        captable=None, register=None, pool_docs=[],
        cla_extraction={"clas": [loan]}, assessment={}, aggregation={}, validation=[])
    insight = build_insight("comments-co", "consolidated")
    insight.save(json.dumps(result))
    assert read_build_insight(insight)["convertibles"][0]["comments"] == QUOTE
    assert loan["comments"] == QUOTE


def test_final_report_copies_comments_and_preserves_calculations():
    data = _snapshot()
    before = build_scenarios(data, valuation_date=date(2026, 9, 8))
    data["convertibles"][0]["comments"] = QUOTE
    untouched = deepcopy(data)
    computed = _computed(data)
    output = render_report(data, computed, "Narrative without the quote.")
    assert " Cap | Comments |" in output
    assert 'Tenity shall hold 2.5% post-money.<br>The basis is A \\| B &lt; C &amp; D.' in output
    assert "Quoted provisions in Comments are not incorporated into the calculations and may require manual adjustment." in output
    assert data == untouched
    after = build_scenarios(data, valuation_date=date(2026, 9, 8))
    # Content fingerprint should change, financial outputs should not.
    before.pop("snapshot_fingerprint")
    after.pop("snapshot_fingerprint")
    assert after == before


@pytest.mark.parametrize("value", [None, "", "missing"])
def test_empty_and_legacy_comments_render_blank(value):
    data = _snapshot()
    if value != "missing":
        data["convertibles"][0]["comments"] = value
    output = render_report(data, _computed(data), "Notes")
    row = next(line for line in output.splitlines() if line.startswith("| cla.md | executed |"))
    assert row.endswith(" |  |")

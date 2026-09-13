"""Caller schemas gate business review through the actual generation pipeline."""
import json
from unittest.mock import AsyncMock, Mock

import pytest

from lib.infrastructure.ai_text_generation import generation
from lib.infrastructure.configuration import load_repository_config
from skills.ranking.ranking_rationale import _review_rationales, _specialize_schema
from skills.ranking.ranking_top_k import _review_ranking
from skills.submission_ready.submission_ready import _review_proposed_action


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [[], {}, {"results": [{"id": "a", "rationale": "  "}]}])
async def test_schema_retry_precedes_business_review(mock_env, monkeypatch, invalid):
    schema = _specialize_schema(
        load_repository_config("ranking_rationale")["response_schema"], ["a"]
    )
    valid = {"results": [{"id": "a", "rationale": "Strong fit."}]}
    request = AsyncMock(side_effect=[
        json.dumps(invalid), json.dumps({"reasoning": "Correct fields.", **valid}),
    ])
    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model:1b")
    monkeypatch.setattr(generation, "_request_text_waiting_out_rate_limits", request)
    reviewer = Mock(side_effect=lambda output: _review_rationales(output, expected_ids=["a"]))
    assert await generation.generate_json("Rank profiles", schema, reviewer) == valid
    assert request.await_count == 2
    reviewer.assert_called_once_with(valid)


def test_ranking_business_repair_preserves_first_occurrence_and_input_order():
    review = _review_ranking(
        {"ranked_profiles_ids": ["b", "b", "b"]}, expected_ids=["a", "b", "c"]
    )
    assert not review.problems
    assert review.output == {"ranked_profiles_ids": ["b", "a", "c"]}


def test_rationale_business_review_requires_unique_coverage():
    review = _review_rationales(
        {"results": [{"id": "a", "rationale": "Fit"}] * 2}, expected_ids=["a", "b"]
    )
    assert review.problems == ("Duplicate rationale IDs.", "Missing rationale IDs: b")


def test_submission_reviewer_returns_normalized_payload():
    review = _review_proposed_action({
        "proposed_action": "Send concerns to startup", "rationale": " Missing evidence. ",
        "eligibility_concerns": ["  ", " Confirm eligibility. "],
        "missing_or_inconsistent_information": [],
    })
    assert not review.problems
    assert review.output["rationale"] == "Missing evidence."
    assert review.output["eligibility_concerns"] == ["Confirm eligibility."]


def test_submission_blank_concerns_do_not_support_sending():
    review = _review_proposed_action({
        "proposed_action": "Send concerns to startup", "rationale": "Missing evidence.",
        "eligibility_concerns": ["  "], "missing_or_inconsistent_information": [],
    })
    assert review.problems == ("Sending concerns requires at least one stated concern.",)


@pytest.mark.asyncio
async def test_sha_condition_is_local_and_still_retries_before_review(mock_env, monkeypatch):
    from copy import deepcopy
    from lib.infrastructure.ai_text_generation.json import json_schema_response_format
    from skills.sha_review.sha_review import _review_identification

    schema = load_repository_config('sha_review')['document_identification_response_schema']
    original = deepcopy(schema)
    valid = {'path': 'agreement.pdf', 'document_match': 'High', 'concerns': [],
             'paths_for_alternative_candidates': [], 'selection_reason': 'Agreement terms.'}
    invalid = {**valid, 'path': None}
    request = AsyncMock(side_effect=[json.dumps(invalid), json.dumps({'reasoning': 'Fix path.', **valid})])
    monkeypatch.setenv('RANKED_LLMS', 'ollama/test-model:1b')
    monkeypatch.setattr(generation, '_request_text_waiting_out_rate_limits', request)
    reviewer = Mock(side_effect=_review_identification)
    assert await generation.generate_json('Identify SHA', schema, reviewer) == valid
    assert request.await_count == 2
    reviewer.assert_called_once_with(valid)
    for call in request.await_args_list:
        sent = call.kwargs['response_format']['json_schema']['schema']
        assert not {'if', 'then', 'else'} & sent.keys()
        assert '"if"' in call.kwargs['prompt']
    assert schema == original
    assert json_schema_response_format(schema)['json_schema']['schema']['required'] == schema['required']


def test_provider_schema_preserves_named_fields_and_literal_objects():
    from copy import deepcopy
    from lib.infrastructure.ai_text_generation.json import json_schema_response_format

    conditional = {'type': 'string', 'if': {'const': 'x'}, 'then': {'minLength': 1}}
    schema = {'type': 'object', 'properties': {'if': conditional, 'then': {'const': {'if': 'literal'}}},
              '$defs': {'else': {'type': 'array', 'items': conditional}},
              'required': ['if', 'then']}
    original = deepcopy(schema)
    sent = json_schema_response_format(schema)['json_schema']['schema']
    assert sent['properties']['if'] == {'type': 'string'}
    assert sent['properties']['then']['const'] == {'if': 'literal'}
    assert sent['$defs']['else']['items'] == {'type': 'string'}
    assert schema == original

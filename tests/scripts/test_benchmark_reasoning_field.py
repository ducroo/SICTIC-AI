from __future__ import annotations

import asyncio
from copy import deepcopy

import scripts.benchmark_reasoning_field as benchmark
from scripts.benchmark_reasoning_field import (
    CONDITIONS,
    Assessment,
    BenchmarkCase,
    add_reasoning_field,
    assess_output,
    build_cases,
    _parse_conditions,
    summarize,
)
from lib.infrastructure.ai_text_generation import Review


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"decision": {"type": "string"}},
    "required": ["decision"],
}


def test_add_reasoning_field_is_first_and_does_not_mutate_business_schema():
    original = deepcopy(SCHEMA)

    transformed = add_reasoning_field(SCHEMA)

    assert next(iter(transformed["properties"])) == "reasoning"
    assert transformed["required"][0] == "reasoning"
    assert SCHEMA == original


def test_assess_output_strips_reasoning_before_business_validation():
    case = BenchmarkCase(
        case_id="fixture",
        workflow="fixture",
        prompt="Prompt",
        schema=SCHEMA,
        reviewer=lambda output: Review(output),
        gold_check=lambda output: output == {"decision": "approve"},
    )

    result = assess_output(
        '{"reasoning":"Evidence supports it","decision":"approve"}',
        case,
        CONDITIONS[1],
    )

    assert result == Assessment(
        raw_json_valid=True,
        technical_parse_valid=True,
        active_schema_valid=True,
        original_schema_valid=True,
        reasoning_present=True,
        reasoning_was_first=True,
        reviewer_pass=True,
        reviewer_corrected=False,
        gold_pass=True,
        overall_pass=True,
        error_stage=None,
    )


def test_build_cases_covers_five_workflows():
    cases = build_cases(2)

    assert len(cases) == 10
    assert {case.workflow for case in cases} == {
        "ranking_top_k",
        "ranking_rationale",
        "batch_audit",
        "sha_template_ranking",
        "submission_ready",
    }


def test_parse_conditions_selects_requested_conditions():
    assert [condition.key for condition in _parse_conditions("A,B")] == ["A", "B"]


def test_summarize_reports_paired_disagreements():
    records = [
        {
            "case_id": "one",
            "condition": condition,
            "overall_pass": condition in {"B", "C", "D"},
            "raw_json_valid": True,
            "original_schema_valid": True,
            "reviewer_pass": True,
            "reviewer_corrected": False,
            "gold_pass": True,
            "wall_seconds": 1.0,
            "output_characters": 10,
            "reasoning_characters": 5,
            "error_stage": None,
        }
        for condition in "ABCD"
    ]

    summary = summarize(records)

    assert summary["conditions"]["A"]["overall_rate"] == 0.0
    assert summary["conditions"]["B"]["overall_rate"] == 1.0
    assert summary["paired_disagreements"]["B_vs_A"] == {
        "both_pass": 0,
        "treatment_only_pass": 1,
        "control_only_pass": 0,
        "both_fail": 0,
    }


def test_run_benchmark_bounds_parallel_requests(monkeypatch, tmp_path):
    active = 0
    maximum_active = 0

    async def fake_chat(**_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"message": {"content": "{}", "thinking": ""}}

    monkeypatch.setattr(benchmark, "_ollama_chat", fake_chat)

    records = asyncio.run(
        benchmark.run_benchmark(
            model="fixture",
            ollama_url="http://fixture",
            cases_per_workflow=1,
            output_file=tmp_path / "results.jsonl",
            timeout=1,
            parallel=2,
            limit=1,
        )
    )

    assert len(records) == 4
    assert maximum_active == 2

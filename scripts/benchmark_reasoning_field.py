"""Screen whether a leading reasoning field helps local structured output.

This diagnostic intentionally bypasses generate_json retries so that recovery
does not hide first-attempt failures. It stores metrics, never prompts, model
content, or reasoning traces.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import statistics
import time
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.infrastructure.ai_text_generation import Review
from lib.infrastructure.ai_text_generation.json import (
    repair_json_payload,
    schema_prompt_block,
    validate_json_schema,
)
from lib.infrastructure.configuration import load_repository_config
from lib.batch_audit.engine import (
    _review_check_response,
    _specialize_response_schema,
)
from skills.ranking.ranking_rationale import (
    _review_rationales,
    _specialize_schema as _rationale_schema,
)
from skills.ranking.ranking_top_k import (
    _review_ranking,
    _specialize_schema as _ranking_schema,
)
from skills.sha_review.sha_review import (
    _review_template_ranking,
    _template_ranking_prompt,
    _template_response_schema,
)
from skills.submission_ready.submission_ready import (
    _proposed_action_prompt,
    _review_proposed_action,
    _specialize_proposed_action_schema,
)


DEFAULT_MODEL = "qwen3.5:4b-mlx"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
STATUS_SCALE = [
    "Confirmed",
    "Partially confirmed",
    "Not confirmed",
    "Not applicable",
]
REASONING_DESCRIPTION = (
    "Briefly analyze the supplied evidence and constraints before producing "
    "the requested business fields."
)
REASONING_INSTRUCTION = (
    "The response schema contains a temporary `reasoning` field. Generate "
    "that field first and use it to analyze the request before generating "
    "the remaining fields. Return only the JSON object."
)


@dataclass(frozen=True)
class Condition:
    key: str
    native_thinking: bool
    schema_reasoning: bool


CONDITIONS = (
    Condition("A", native_thinking=False, schema_reasoning=False),
    Condition("B", native_thinking=False, schema_reasoning=True),
    Condition("C", native_thinking=True, schema_reasoning=False),
    Condition("D", native_thinking=True, schema_reasoning=True),
)


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    workflow: str
    prompt: str
    schema: dict[str, Any]
    reviewer: Callable[[dict | list], Review[dict | list]]
    gold_check: Callable[[dict | list], bool] | None = None


@dataclass(frozen=True)
class Assessment:
    raw_json_valid: bool
    technical_parse_valid: bool
    active_schema_valid: bool
    original_schema_valid: bool
    reasoning_present: bool | None
    reasoning_was_first: bool | None
    reviewer_pass: bool
    reviewer_corrected: bool
    gold_pass: bool | None
    overall_pass: bool
    error_stage: str | None


def add_reasoning_field(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an object schema with a required reasoning property first."""
    if schema.get("type") != "object" or not isinstance(
        schema.get("properties"), dict
    ):
        raise ValueError("Reasoning-field screening requires an object schema")
    if "reasoning" in schema["properties"]:
        raise ValueError("The business schema already defines `reasoning`")
    transformed = deepcopy(schema)
    transformed["properties"] = {
        "reasoning": {
            "type": "string",
            "minLength": 1,
            "description": REASONING_DESCRIPTION,
        },
        **transformed["properties"],
    }
    required = list(transformed.get("required", []))
    transformed["required"] = [
        "reasoning",
        *(item for item in required if item != "reasoning"),
    ]
    return transformed


def assess_output(
    raw_output: str,
    case: BenchmarkCase,
    condition: Condition,
) -> Assessment:
    """Assess one output while keeping response content out of stored data."""
    active_schema = (
        add_reasoning_field(case.schema)
        if condition.schema_reasoning
        else case.schema
    )
    raw_json_valid = False
    try:
        direct = json.loads(raw_output)
        raw_json_valid = isinstance(direct, (dict, list))
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        parsed = repair_json_payload(raw_output)
    except ValueError:
        return _failed_assessment(raw_json_valid, "technical_parse")

    try:
        validate_json_schema(parsed, active_schema, label="Benchmark response")
    except ValueError:
        return _failed_assessment(
            raw_json_valid,
            "active_schema",
            technical_parse_valid=True,
        )

    reasoning_present: bool | None = None
    reasoning_was_first: bool | None = None
    business_output = deepcopy(parsed)
    if condition.schema_reasoning:
        reasoning_present = (
            isinstance(parsed, dict)
            and isinstance(parsed.get("reasoning"), str)
            and bool(parsed["reasoning"].strip())
        )
        reasoning_was_first = (
            isinstance(parsed, dict)
            and bool(parsed)
            and next(iter(parsed)) == "reasoning"
        )
        if isinstance(business_output, dict):
            business_output.pop("reasoning", None)

    try:
        validate_json_schema(
            business_output,
            case.schema,
            label="Benchmark business response",
        )
    except ValueError:
        return Assessment(
            raw_json_valid=raw_json_valid,
            technical_parse_valid=True,
            active_schema_valid=True,
            original_schema_valid=False,
            reasoning_present=reasoning_present,
            reasoning_was_first=reasoning_was_first,
            reviewer_pass=False,
            reviewer_corrected=False,
            gold_pass=None,
            overall_pass=False,
            error_stage="original_schema",
        )

    review = case.reviewer(business_output)
    reviewer_pass = not review.problems
    reviewer_corrected = review.output != business_output
    gold_pass = (
        case.gold_check(review.output) if case.gold_check is not None else None
    )
    overall_pass = (
        reviewer_pass
        and not reviewer_corrected
        and gold_pass is not False
    )
    return Assessment(
        raw_json_valid=raw_json_valid,
        technical_parse_valid=True,
        active_schema_valid=True,
        original_schema_valid=True,
        reasoning_present=reasoning_present,
        reasoning_was_first=reasoning_was_first,
        reviewer_pass=reviewer_pass,
        reviewer_corrected=reviewer_corrected,
        gold_pass=gold_pass,
        overall_pass=overall_pass,
        error_stage=None if overall_pass else "business_review",
    )


def _failed_assessment(
    raw_json_valid: bool,
    stage: str,
    *,
    technical_parse_valid: bool = False,
) -> Assessment:
    return Assessment(
        raw_json_valid=raw_json_valid,
        technical_parse_valid=technical_parse_valid,
        active_schema_valid=False,
        original_schema_valid=False,
        reasoning_present=None,
        reasoning_was_first=None,
        reviewer_pass=False,
        reviewer_corrected=False,
        gold_pass=None,
        overall_pass=False,
        error_stage=stage,
    )


def build_cases(cases_per_workflow: int = 10) -> list[BenchmarkCase]:
    """Build synthetic cases using the repository's real schema families."""
    builders = (
        _ranking_cases,
        _rationale_cases,
        _audit_cases,
        _sha_cases,
        _submission_cases,
    )
    cases = [
        case
        for builder in builders
        for case in builder(cases_per_workflow)
    ]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Benchmark case IDs must be unique")
    return cases


def _profile_fixture(index: int) -> tuple[str, dict[str, str], list[str]]:
    objectives = (
        "Rank candidates for enterprise-software go-to-market expertise.",
        "Rank candidates for regulated medical-device commercialization.",
        "Rank candidates for industrial hardware manufacturing scale-up.",
        "Rank candidates for early-stage venture financing experience.",
        "Rank candidates for machine-learning product leadership.",
    )
    themes = (
        "enterprise SaaS sales and channel partnerships",
        "medical-device regulation and hospital procurement",
        "industrial production and supply-chain scale-up",
        "venture financing and startup board work",
        "machine-learning products and engineering leadership",
    )
    objective = objectives[index % len(objectives)]
    theme = themes[index % len(themes)]
    ids = [f"candidate-{index:02d}-{letter}" for letter in "ABCD"]
    profiles = {
        ids[0]: f"Twelve years leading {theme}; two successful scale-ups.",
        ids[1]: f"Four years supporting {theme}; strong adjacent experience.",
        ids[2]: "Experienced operator in an unrelated consumer-services field.",
        ids[3]: f"Academic familiarity with {theme}, without operating experience.",
    }
    return objective, profiles, ids


def _ranking_cases(count: int) -> list[BenchmarkCase]:
    section = load_repository_config("ranking_top_k")
    cases: list[BenchmarkCase] = []
    for index in range(count):
        objective, profiles, ids = _profile_fixture(index)
        profiles_text = "\n\n".join(
            f"ID: {profile_id}\n{text}"
            for profile_id, text in profiles.items()
        )
        prompt = (
            section["ranking_instructions"]
            .replace("{{profiles_text}}", profiles_text)
            .replace("{{objective}}", objective)
            .replace("{{n_profiles}}", str(len(profiles)))
            .replace("{{IDs_profiles}}", ", ".join(ids))
            + "\n\nReturn every supplied profile ID exactly once."
        )
        cases.append(
            BenchmarkCase(
                case_id=f"ranking-{index:02d}",
                workflow="ranking_top_k",
                prompt=prompt,
                schema=_ranking_schema(section["response_schema"], ids),
                reviewer=lambda output, ids=ids: _review_ranking(
                    output,
                    expected_ids=ids,
                ),
                gold_check=lambda output, best=ids[0]: (
                    isinstance(output, dict)
                    and output.get("ranked_profiles_ids", [None])[0] == best
                ),
            )
        )
    return cases


def _rationale_cases(count: int) -> list[BenchmarkCase]:
    section = load_repository_config("ranking_rationale")
    cases: list[BenchmarkCase] = []
    for index in range(count):
        objective, profiles, ids = _profile_fixture(index)
        profiles_text = "\n\n---\n\n".join(
            f"### Rank {rank} | Profile ID: {profile_id}\n\n"
            f"{profiles[profile_id]}"
            for rank, profile_id in enumerate(ids, start=1)
        )
        prompt = (
            section["rationale_instructions"]
            .replace("{{profiles_text}}", profiles_text)
            .replace("{{objective}}", objective)
        )
        cases.append(
            BenchmarkCase(
                case_id=f"rationale-{index:02d}",
                workflow="ranking_rationale",
                prompt=prompt,
                schema=_rationale_schema(section["response_schema"], ids),
                reviewer=lambda output, ids=ids: _review_rationales(
                    output,
                    expected_ids=ids,
                ),
            )
        )
    return cases


def _audit_cases(count: int) -> list[BenchmarkCase]:
    section = load_repository_config("batch_audit")
    situations = (
        (
            "Confirm that recurring revenue is evidenced.",
            "The signed customer schedule lists recurring annual fees.",
            "Confirmed",
        ),
        (
            "Confirm that intellectual property is assigned to the company.",
            "Two founders signed assignments; one founder agreement is missing.",
            "Partially confirmed",
        ),
        (
            "Confirm that regulatory approval has been obtained.",
            "No regulatory approval or application is present in the evidence.",
            "Not confirmed",
        ),
        (
            "Assess manufacturing certification.",
            "The company supplies software only and manufactures no products.",
            "Not applicable",
        ),
    )
    schema = _specialize_response_schema(
        section["response_schema"],
        STATUS_SCALE,
    )
    cases: list[BenchmarkCase] = []
    for index in range(count):
        check, evidence, expected = situations[index % len(situations)]
        prompt = (
            f"{section['llm_instructions']}\n\n"
            f"### DATASET EVIDENCE\n{evidence}\n\n"
            f"### CURRENT CHECK\n{check}\n\n"
            "Use the exact evidence status represented by the supplied facts."
        )
        cases.append(
            BenchmarkCase(
                case_id=f"audit-{index:02d}",
                workflow="batch_audit",
                prompt=prompt,
                schema=deepcopy(schema),
                reviewer=lambda output: _review_check_response(
                    output,
                    STATUS_SCALE,
                ),
                gold_check=lambda output, expected=expected: (
                    isinstance(output, dict)
                    and output.get("status") == expected
                ),
            )
        )
    return cases


def _sha_cases(count: int) -> list[BenchmarkCase]:
    section = load_repository_config("sha_review")
    cases: list[BenchmarkCase] = []
    for index in range(count):
        keys = [f"template-{index:02d}-{letter}" for letter in "ABC"]
        templates = {
            keys[0]: (
                "Seed financing with one preferred share class, a three-seat "
                "board, broad-based weighted-average anti-dilution and a 1x "
                "non-participating liquidation preference."
            ),
            keys[1]: (
                "Mature-company agreement with multiple investor classes, a "
                "five-seat board and participating liquidation preferences."
            ),
            keys[2]: (
                "Founder-only ordinary-share agreement without investor "
                "preferences, anti-dilution or institutional governance."
            ),
        }
        reviewed = templates[keys[0]] + " Includes customary drag and tag rights."
        prompt = _template_ranking_prompt(
            reviewed,
            templates,
            section["template_ranking_prompt"],
        )
        cases.append(
            BenchmarkCase(
                case_id=f"sha-{index:02d}",
                workflow="sha_template_ranking",
                prompt=prompt,
                schema=_template_response_schema(
                    section["template_ranking_response_schema"],
                    keys,
                ),
                reviewer=lambda output, keys=keys: _review_template_ranking(
                    output,
                    keys,
                ),
                gold_check=lambda output, best=keys[0]: (
                    isinstance(output, dict)
                    and bool(output.get("rankings"))
                    and output["rankings"][0].get("template_key") == best
                ),
            )
        )
    return cases


def _submission_cases(count: int) -> list[BenchmarkCase]:
    section = load_repository_config("submission_ready")
    cases: list[BenchmarkCase] = []
    for index in range(count):
        stage = "Application" if index % 2 == 0 else "Under review"
        ready = index % 3 != 0
        checklist = (
            "All mandatory fields are complete. Team, incorporation and "
            "financing evidence are internally consistent. No concerns found."
            if ready
            else (
                "The incorporation document is missing and the stated funding "
                "amount conflicts with the financial schedule."
            )
        )
        expected = (
            "Move to Under review"
            if ready and stage == "Application"
            else "Move to Jury"
            if ready
            else "Send concerns to startup"
        )
        prompt = _proposed_action_prompt(
            stage=stage,
            checklist_report=checklist,
            response_instructions=section["response_instructions"],
        )
        cases.append(
            BenchmarkCase(
                case_id=f"submission-{index:02d}",
                workflow="submission_ready",
                prompt=prompt,
                schema=_specialize_proposed_action_schema(
                    section["response_schema"],
                    stage,
                ),
                reviewer=lambda output, stage=stage: _review_proposed_action(
                    output,
                    stage,
                ),
                gold_check=lambda output, expected=expected: (
                    isinstance(output, dict)
                    and output.get("proposed_action") == expected
                ),
            )
        )
    return cases


async def _ollama_chat(
    *,
    ollama_url: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    think: bool,
    seed: int,
    timeout: float,
    num_ctx: int,
    num_predict: int,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
        "format": schema,
        "options": {
            "seed": seed,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }

    def request() -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        url = ollama_url.rstrip("/") + "/api/chat"
        http_request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ValueError("Ollama response must be an object")
        return result

    return await asyncio.to_thread(request)


async def run_benchmark(
    *,
    model: str,
    ollama_url: str,
    cases_per_workflow: int,
    output_file: Path,
    timeout: float,
    parallel: int = 1,
    conditions: tuple[Condition, ...] = CONDITIONS,
    num_ctx: int = 32768,
    num_predict: int = 4096,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if parallel < 1:
        raise ValueError("parallel must be at least 1")
    cases = build_cases(cases_per_workflow)
    if limit is not None:
        cases = cases[:limit]
    completed = _read_results(output_file)
    completed_keys = {
        (str(item["case_id"]), str(item["condition"]))
        for item in completed
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    done = len(completed_keys)
    jobs: list[tuple[int, BenchmarkCase, Condition]] = []
    for case_index, case in enumerate(cases):
        case_conditions = list(conditions)
        random.Random(10_000 + case_index).shuffle(case_conditions)
        for condition in case_conditions:
            key = (case.case_id, condition.key)
            if key in completed_keys:
                continue
            jobs.append((case_index, case, condition))
    total = done + len(jobs)

    semaphore = asyncio.Semaphore(parallel)

    async def execute(
        case_index: int,
        case: BenchmarkCase,
        condition: Condition,
    ) -> tuple[tuple[str, str], dict[str, Any]]:
        key = (case.case_id, condition.key)
        async with semaphore:
            active_schema = (
                add_reasoning_field(case.schema)
                if condition.schema_reasoning
                else case.schema
            )
            prompt_parts = [case.prompt]
            if condition.schema_reasoning:
                prompt_parts.append(REASONING_INSTRUCTION)
            prompt_parts.append(schema_prompt_block(active_schema))
            full_prompt = "\n\n".join(prompt_parts)
            started = time.monotonic()
            provider: dict[str, Any] | None = None
            request_error: str | None = None
            try:
                provider = await _ollama_chat(
                    ollama_url=ollama_url,
                    model=model,
                    prompt=full_prompt,
                    schema=active_schema,
                    think=condition.native_thinking,
                    seed=20_000 + case_index,
                    timeout=timeout,
                    num_ctx=num_ctx,
                    num_predict=num_predict,
                )
                message = provider.get("message") or {}
                content = str(message.get("content") or "")
                thinking = str(message.get("thinking") or "")
                assessment = assess_output(content, case, condition)
            except Exception as error:
                content = ""
                thinking = ""
                request_error = type(error).__name__
                assessment = _failed_assessment(False, "provider_request")
            wall_seconds = time.monotonic() - started
            record = {
                "schema_version": 1,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "case_id": case.case_id,
                "workflow": case.workflow,
                "condition": condition.key,
                "native_thinking": condition.native_thinking,
                "schema_reasoning": condition.schema_reasoning,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "input_characters": len(full_prompt),
                "output_characters": len(content),
                "reasoning_characters": len(thinking),
                "wall_seconds": wall_seconds,
                "request_error": request_error,
                "content_digest": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest()[:16],
                **asdict(assessment),
                **_provider_metrics(provider),
            }
        return key, record

    tasks = [
        asyncio.create_task(execute(case_index, case, condition))
        for case_index, case, condition in jobs
    ]
    for task in asyncio.as_completed(tasks):
        key, record = await task
        _append_record(output_file, record)
        completed.append(record)
        completed_keys.add(key)
        done += 1
        print(
            f"[{done:03d}/{total:03d}] {record['case_id']} "
            f"{record['condition']}: "
            f"{'PASS' if record['overall_pass'] else 'FAIL'} "
            f"({record['wall_seconds']:.1f}s, "
            f"stage={record['error_stage'] or 'none'})",
            flush=True,
        )
    return completed


def _provider_metrics(provider: dict[str, Any] | None) -> dict[str, Any]:
    provider = provider or {}
    return {
        "done_reason": provider.get("done_reason"),
        "load_duration_ns": provider.get("load_duration"),
        "prompt_eval_count": provider.get("prompt_eval_count"),
        "prompt_eval_duration_ns": provider.get("prompt_eval_duration"),
        "eval_count": provider.get("eval_count"),
        "eval_duration_ns": provider.get("eval_duration"),
        "total_duration_ns": provider.get("total_duration"),
    }


def _append_record(path: Path, record: dict[str, Any]) -> None:
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded + "\n")


def _read_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_condition[str(record["condition"])].append(record)
    conditions: dict[str, Any] = {}
    for key in sorted(by_condition):
        items = by_condition[key]
        gold = [item for item in items if item.get("gold_pass") is not None]
        conditions[key] = {
            "calls": len(items),
            "raw_json_rate": _rate(items, "raw_json_valid"),
            "schema_rate": _rate(items, "original_schema_valid"),
            "reviewer_rate": _rate(items, "reviewer_pass"),
            "uncorrected_rate": sum(
                bool(item.get("reviewer_pass"))
                and not bool(item.get("reviewer_corrected"))
                for item in items
            )
            / len(items),
            "gold_rate": _rate(gold, "gold_pass") if gold else None,
            "overall_rate": _rate(items, "overall_pass"),
            "mean_wall_seconds": statistics.fmean(
                float(item["wall_seconds"]) for item in items
            ),
            "mean_output_characters": statistics.fmean(
                int(item["output_characters"]) for item in items
            ),
            "mean_reasoning_characters": statistics.fmean(
                int(item["reasoning_characters"]) for item in items
            ),
            "failures_by_stage": dict(
                Counter(
                    str(item.get("error_stage") or "none") for item in items
                )
            ),
        }
    return {
        "schema_version": 1,
        "records": len(records),
        "conditions": conditions,
        "paired_disagreements": _paired_disagreements(records),
    }


def _rate(items: list[dict[str, Any]], field: str) -> float:
    return sum(bool(item.get(field)) for item in items) / len(items)


def _paired_disagreements(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, dict[str, bool]] = defaultdict(dict)
    for item in records:
        by_case[str(item["case_id"])][str(item["condition"])] = bool(
            item.get("overall_pass")
        )
    comparisons = ("BA", "CA", "CB", "DC")
    result: dict[str, Any] = {}
    for comparison in comparisons:
        treatment, control = comparison
        pairs = [
            values
            for values in by_case.values()
            if treatment in values and control in values
        ]
        result[f"{treatment}_vs_{control}"] = {
            "both_pass": sum(
                pair[treatment] and pair[control] for pair in pairs
            ),
            "treatment_only_pass": sum(
                pair[treatment] and not pair[control] for pair in pairs
            ),
            "control_only_pass": sum(
                not pair[treatment] and pair[control] for pair in pairs
            ),
            "both_fail": sum(
                not pair[treatment] and not pair[control] for pair in pairs
            ),
        }
    return result


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Reasoning-field screening summary",
        "",
        "| Condition | Calls | JSON | Schema | Reviewer | Gold | Overall | Mean seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, item in summary["conditions"].items():
        gold = item["gold_rate"]
        lines.append(
            f"| {key} | {item['calls']} | {item['raw_json_rate']:.1%} | "
            f"{item['schema_rate']:.1%} | {item['reviewer_rate']:.1%} | "
            f"{gold:.1%} | {item['overall_rate']:.1%} | "
            f"{item['mean_wall_seconds']:.1f} |"
            if gold is not None
            else (
                f"| {key} | {item['calls']} | {item['raw_json_rate']:.1%} | "
                f"{item['schema_rate']:.1%} | {item['reviewer_rate']:.1%} | — | "
                f"{item['overall_rate']:.1%} | {item['mean_wall_seconds']:.1f} |"
            )
        )
    lines.extend(["", "## Paired disagreements", ""])
    for name, counts in summary["paired_disagreements"].items():
        lines.append(
            f"- {name}: treatment only {counts['treatment_only_pass']}; "
            f"control only {counts['control_only_pass']}"
        )
    return "\n".join(lines) + "\n"


async def _main(args: argparse.Namespace) -> int:
    output_file = Path(args.output)
    records = await run_benchmark(
        model=args.model,
        ollama_url=args.ollama_url,
        cases_per_workflow=args.cases_per_workflow,
        output_file=output_file,
        timeout=args.timeout,
        parallel=args.parallel,
        conditions=args.conditions,
        num_ctx=args.num_ctx,
        num_predict=args.num_predict,
        limit=args.limit,
    )
    summary = summarize(records)
    summary_json = output_file.with_suffix(".summary.json")
    summary_markdown = output_file.with_suffix(".summary.md")
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_markdown.write_text(_summary_markdown(summary), encoding="utf-8")
    print(f"Results: {output_file}")
    print(f"Summary: {summary_markdown}")
    return 0


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--cases-per-workflow", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument(
        "--conditions",
        type=_parse_conditions,
        default=CONDITIONS,
        help="Condition keys to run, such as AB or CD",
    )
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output",
        default=(
            "logs/benchmarks/reasoning-field-"
            f"{DEFAULT_MODEL.replace(':', '-')}-{timestamp}.jsonl"
        ),
    )
    return asyncio.run(_main(parser.parse_args()))


def _parse_conditions(value: str) -> tuple[Condition, ...]:
    keys = [character for character in value.upper() if character not in ", "]
    known = {condition.key: condition for condition in CONDITIONS}
    if not keys or len(set(keys)) != len(keys) or any(
        key not in known for key in keys
    ):
        raise argparse.ArgumentTypeError(
            "conditions must contain unique keys selected from A, B, C and D"
        )
    return tuple(known[key] for key in keys)


if __name__ == "__main__":
    raise SystemExit(main())

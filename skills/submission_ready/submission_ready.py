from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

from lib.batch_audit import batch_audit
from lib.batch_audit.checklist import parse_checklist
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import audit_errors, validate_audit_document
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import (
    dataset_location_for_domain,
    dataset_raw_path,
    find_dataset_location,
)
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.ai_text_generation.json import copy_schema
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.insights.paths import model_slug
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.startups.dealum import (
    DealumApplicationNotFoundError,
    DealumMatch,
    DealumReconciliationError,
    import_startup_from_dealum,
    reconcile_dealum_startup,
)
from lib.storage import get_storage

logger = get_logger(__name__)

IN_SCOPE_STAGES = {
    "application": "Application",
    "under review": "Under review",
}
MAX_ATTEMPTS = 3
MAX_CONCERNS = 8

T = TypeVar("T")


@dataclass(frozen=True)
class SubmissionReadyResult:
    startup: str
    stage: str | None
    status: str
    checklist_path: str | None = None
    response_path: str | None = None
    error: str | None = None
    insights: tuple[InsightFile, ...] = ()


def _run_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalized_stage(value: Any) -> str:
    return " ".join(
        str(value or "")
        .replace("_", " ")
        .replace("-", " ")
        .casefold()
        .split()
    )


def _canonical_stage(value: Any) -> str | None:
    return IN_SCOPE_STAGES.get(_normalized_stage(value))


async def _retry(
    label: str,
    operation: Callable[[], T | Awaitable[T]],
) -> T:
    errors: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = operation()
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception as error:
            errors.append(str(error))
            logger.warning(
                "%s failed on attempt %d/%d: %s",
                label,
                attempt,
                MAX_ATTEMPTS,
                error,
            )
    raise RuntimeError(
        f"{label} failed after {MAX_ATTEMPTS} attempts: "
        + " | ".join(errors)
    )


def _table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _insight_for_run(
    startup_slug: str,
    *,
    identifier: str,
    run_id: str,
    config_key: str,
) -> InsightFile:
    return InsightFile(
        dataset=startup_slug,
        skill="submission_ready",
        model=llm_model(),
        identifier=identifier,
        subdir=True,
        run_id=run_id,
        config_key=config_key,
    )


def _reusable_run_insight(
    startup_slug: str,
    *,
    identifier: str,
    config_key: str,
) -> InsightFile | None:
    storage = get_storage()
    root = InsightFile(
        dataset=startup_slug,
        skill="submission_ready",
        model=llm_model(),
        identifier=identifier,
        subdir=True,
        config_key=config_key,
    ).directory
    for run_id in reversed(storage.list(root)):
        run_path = f"{root}/{run_id}"
        if not storage.is_dir(run_path):
            continue
        candidate = _insight_for_run(
            startup_slug,
            identifier=identifier,
            run_id=run_id,
            config_key=config_key,
        )
        if candidate.is_reusable():
            return candidate
    return None


def _normalize_concerns(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_proposed_action(
    result: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    action = str(result.get("proposed_action", "")).strip()
    allowed_actions = {
        "Application": {
            "Move to Under review",
            "Send concerns to startup",
        },
        "Under review": {
            "Move to Jury",
            "Send concerns to startup",
        },
    }[stage]
    if action not in allowed_actions:
        raise ValueError(
            f"Invalid proposed action {action!r} for stage {stage!r}."
        )

    rationale = str(result.get("rationale", "")).strip()
    if not rationale:
        raise ValueError("The proposed action requires a rationale.")
    eligibility = _normalize_concerns(
        result.get("eligibility_concerns"),
        "eligibility_concerns",
    )
    incomplete = _normalize_concerns(
        result.get("missing_or_inconsistent_information"),
        "missing_or_inconsistent_information",
    )
    if len(eligibility) + len(incomplete) > MAX_CONCERNS:
        raise ValueError(
            f"The proposed action contains more than {MAX_CONCERNS} concerns."
        )
    if action == "Send concerns to startup" and not (
        eligibility or incomplete
    ):
        raise ValueError(
            "Sending concerns requires at least one stated concern."
        )
    return {
        "proposed_action": action,
        "rationale": rationale,
        "eligibility_concerns": eligibility,
        "missing_or_inconsistent_information": incomplete,
    }


def _review_proposed_action(
    output: dict | list,
    stage: str,
) -> Review[dict | list]:
    if not isinstance(output, dict):
        return Review(output, ("Proposed action must be a JSON object",))
    try:
        _parse_proposed_action(output, stage)
    except (KeyError, TypeError, ValueError) as error:
        return Review(output, (str(error),))
    return Review(output)


def _specialize_proposed_action_schema(
    response_schema: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    allowed_actions = {
        "Application": [
            "Move to Under review",
            "Send concerns to startup",
        ],
        "Under review": [
            "Move to Jury",
            "Send concerns to startup",
        ],
    }[stage]
    specialized = copy_schema(response_schema)
    try:
        specialized["properties"]["proposed_action"]["enum"] = (
            allowed_actions
        )
    except (KeyError, TypeError) as error:
        raise ValueError(
            "submission_ready.response_schema must define "
            "properties.proposed_action."
        ) from error
    return specialized


async def _generate_proposed_action(
    *,
    stage: str,
    checklist_report: str,
    response_instructions: str,
    response_schema: dict[str, Any],
) -> tuple[str, str]:
    effective_schema = _specialize_proposed_action_schema(
        response_schema,
        stage,
    )
    prompt = _proposed_action_prompt(
        stage=stage,
        checklist_report=checklist_report,
        response_instructions=response_instructions,
    )
    result = await generate_json(
        prompt,
        effective_schema,
        reviewer=lambda output: _review_proposed_action(output, stage),
    )
    if not isinstance(result, dict):
        raise ValueError("Proposed action must be a JSON object")
    result = _parse_proposed_action(result, stage)

    return _render_proposed_action(stage, result), prompt


def _proposed_action_prompt(
    *,
    stage: str,
    checklist_report: str,
    response_instructions: str,
) -> str:
    return "\n\n".join(
        [
            response_instructions,
            f"Current Dealum stage: {stage}",
            "Current submission checklist:\n" + checklist_report,
        ]
    )


def _render_concerns(concerns: list[str]) -> str:
    if not concerns:
        return "- None identified."
    return "\n".join(
        f"{index}. {concern}"
        for index, concern in enumerate(concerns, start=1)
    )


def _render_proposed_action(
    stage: str,
    result: dict[str, Any],
) -> str:
    return (
        "# Proposed action\n\n"
        f"- Current stage: {stage}\n"
        f"- Proposed action: {result['proposed_action']}\n"
        f"- Rationale: {result['rationale']}\n\n"
        "## Eligibility concerns\n\n"
        f"{_render_concerns(result['eligibility_concerns'])}\n\n"
        "## Missing or inconsistent information\n\n"
        f"{_render_concerns(result['missing_or_inconsistent_information'])}\n"
    )


def _resolve_candidates(
    applications: list[dict[str, Any]],
    adapter: DealumAdapter,
    requested_startups: list[str] | None,
) -> tuple[list[tuple[DealumMatch, str]], list[SubmissionReadyResult]]:
    candidates: list[tuple[DealumMatch, str]] = []
    statuses: list[SubmissionReadyResult] = []
    requested = requested_startups
    if requested is None:
        requested = sorted(
            {
                str(application.get("name") or "").strip()
                for application in applications
                if application.get("name")
            },
            key=str.casefold,
        )

    seen_ids: set[str] = set()
    for startup in requested:
        try:
            match = reconcile_dealum_startup(
                startup,
                adapter=adapter,
                applications=applications,
            )
        except DealumApplicationNotFoundError:
            if requested_startups is not None:
                statuses.append(
                    SubmissionReadyResult(
                        startup=startup,
                        stage=None,
                        status="not found in Dealum; no action",
                    )
                )
            continue
        except DealumReconciliationError as error:
            statuses.append(
                SubmissionReadyResult(
                    startup=startup,
                    stage=None,
                    status="could not resolve Dealum application",
                    error=str(error),
                )
            )
            continue

        stage = _canonical_stage(match.step)
        if stage is None:
            if requested_startups is not None:
                statuses.append(
                    SubmissionReadyResult(
                        startup=match.matched_name,
                        stage=str(match.step or "") or None,
                        status="outside submission-ready stages; no action",
                    )
                )
            continue
        identity = str(match.dealum_id)
        if identity in seen_ids:
            continue
        seen_ids.add(identity)
        candidates.append((match, stage))
    return candidates, statuses


async def _prepare_dataset(
    match: DealumMatch,
    *,
    applications: list[dict[str, Any]],
    adapter: DealumAdapter,
    force_refresh: bool,
) -> str:
    if force_refresh:
        result = await _retry(
            f"[{match.matched_name}] Dealum import",
            lambda: import_startup_from_dealum(
                match.matched_name,
                adapter=adapter,
                applications=applications,
                activate=False,
            ),
        )
        startup_slug = result.dataset_slug
    else:
        from lib.startups.sources import ensure_startup_dataset

        status = await _retry(
            f"[{match.matched_name}] Dealum import",
            lambda: ensure_startup_dataset(
                match.matched_name,
                sync_after_import=False,
                dealum_applications=applications,
                raise_on_error=True,
            ),
        )
        startup_slug = status.dataset_slug

    raw_path = dataset_raw_path(startup_slug)
    if not get_storage().exists(raw_path):
        raise ValueError(
            f"Dataset for {startup_slug} not found at {raw_path}."
        )
    await _retry(
        f"[{match.matched_name}] dataset synchronization",
        lambda: sync_datasets([startup_slug], raise_on_error=True),
    )
    return startup_slug


async def _process_candidate(
    match: DealumMatch,
    stage: str,
    *,
    applications: list[dict[str, Any]],
    adapter: DealumAdapter,
    force_refresh: bool,
    run_id: str,
    check_config: dict[str, Any],
) -> SubmissionReadyResult:
    startup_slug = await _prepare_dataset(
        match,
        applications=applications,
        adapter=adapter,
        force_refresh=force_refresh,
    )
    llm_instructions = (
        f"{check_config['policy']}\n\n"
        f"{check_config['llm_instructions']}"
    )
    audit_insight = await batch_audit(
        dataset_name=startup_slug,
        checklist_markdown=check_config["checklist"],
        skill_name="submission_ready",
        llm_instructions=llm_instructions,
        status_scale=["Pass", "Fail", "Unclear"],
        missing_evidence_status="Unclear",
    )
    audit = validate_audit_document(json.loads(audit_insight.content()))
    failed_checks = audit_errors(audit)
    if failed_checks:
        details = "; ".join(
            f"{check['number']}: {check['error']}"
            for check in failed_checks
        )
        raise RuntimeError(
            f"Submission audit contains {len(failed_checks)} technical "
            f"failure(s): {details}"
        )
    table = json_to_markdown_table(audit_insight)
    checklist_report = (
        "# Completeness and Eligibility Check for "
        f"{match.matched_name}\n\n"
        "Scope: Dealum submission completeness and SICTIC initial "
        "eligibility. This is not a pitch-readiness or "
        "investment-quality assessment.\n\n"
        f"{table}\n"
    )
    checklist_config_key = config_cache_key(
        check_config,
        load_repository_config("structured_output"),
        {
            "artifact": "checklist",
            "audit_path": audit_insight.path,
            "audit": audit,
        },
    )
    response_config_key = config_cache_key(
        check_config,
        load_repository_config("structured_output"),
        {
            "artifact": "response",
            "stage": stage,
            "audit_path": audit_insight.path,
            "audit": audit,
        },
    )
    reusable_response = _reusable_run_insight(
        startup_slug,
        identifier="response",
        config_key=response_config_key,
    )
    if reusable_response is not None:
        reusable_checklist = _insight_for_run(
            startup_slug,
            identifier="checklist",
            run_id=reusable_response.run_id,
            config_key=checklist_config_key,
        )
        if not reusable_checklist.exists():
            reusable_checklist.save(checklist_report)
        return SubmissionReadyResult(
            startup=match.matched_name,
            stage=stage,
            status="unchanged; reused existing analysis",
            checklist_path=reusable_checklist.path,
            response_path=reusable_response.path,
            insights=(reusable_checklist, reusable_response),
        )

    checklist_insight = _insight_for_run(
        startup_slug,
        identifier="checklist",
        run_id=run_id,
        config_key=checklist_config_key,
    )
    checklist_insight.save(checklist_report)

    response_report, _response_prompt = await _generate_proposed_action(
        stage=stage,
        checklist_report=checklist_report,
        response_instructions=check_config["response_instructions"],
        response_schema=check_config["response_schema"],
    )
    response_insight = _insight_for_run(
        startup_slug,
        identifier="response",
        run_id=run_id,
        config_key=response_config_key,
    )
    response_insight.save(response_report)
    return SubmissionReadyResult(
        startup=match.matched_name,
        stage=stage,
        status="generated checklist and proposed action",
        checklist_path=checklist_insight.path,
        response_path=response_insight.path,
        insights=(checklist_insight, response_insight),
    )


def _save_failure_report(
    failures: list[SubmissionReadyResult],
    run_id: str,
) -> InsightFile:
    storage = get_storage()
    location = dataset_location_for_domain(
        "submission-ready-runs",
        "generated",
    )
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.insights_rel)
    report = [
        "# Submission-ready failures",
        "",
        f"Run: {run_id}",
        "",
        "| Startup | Stage | Failed step or error | Older usable result | "
        "Manual action |",
        "|---|---|---|---|---|",
    ]
    for failure in failures:
        older_result = (
            failure.response_path
            or failure.checklist_path
            or "None found"
        )
        report.append(
            f"| {_table_cell(failure.startup)} | "
            f"{_table_cell(failure.stage or 'Unknown')} | "
            f"{_table_cell(failure.error or failure.status)} | "
            f"{_table_cell(older_result)} | "
            "Review the application manually and rerun submission_ready. |"
        )
    insight = InsightFile(
        dataset=location.slug,
        skill="submission_ready",
        model=llm_model(),
        identifier="failures",
        subdir=True,
        run_id=run_id,
        config_key="submission_ready failure report",
    )
    insight.save("\n".join(report) + "\n")
    return insight


def _latest_existing_artifacts(
    startup: str,
) -> tuple[str | None, str | None]:
    location = find_dataset_location(slugify(startup))
    if location is None:
        return None, None
    storage = get_storage()
    root = f"{location.insights_rel}/{slugify('submission_ready')}"
    for run_id in reversed(storage.list(root)):
        if not storage.is_dir(f"{root}/{run_id}"):
            continue
        checklist = InsightFile(
            dataset=location.slug,
            skill="submission_ready",
            model=llm_model(),
            identifier="checklist",
            subdir=True,
            run_id=run_id,
        )
        response = InsightFile(
            dataset=location.slug,
            skill="submission_ready",
            model=llm_model(),
            identifier="response",
            subdir=True,
            run_id=run_id,
        )
        checklist_path = checklist.path if checklist.exists() else None
        response_path = response.path if response.exists() else None
        if checklist_path or response_path:
            return checklist_path, response_path
    try:
        checklist_title = parse_checklist(
            load_repository_config("submission_ready", "checklist")
        ).title
        audit_insight = InsightFile(
            dataset=location.slug,
            skill="batch_audit",
            model=llm_model(),
            identifier=f"submission_ready-{checklist_title}",
            subdir=True,
            extension="json",
        ).find(selection="any")
        if audit_insight is not None:
            audit = validate_audit_document(
                json.loads(audit_insight.content())
            )
            if not audit_errors(audit):
                return audit_insight.path, None
    except (KeyError, ValueError, json.JSONDecodeError):
        logger.warning(
            "[%s] Could not resolve an older structured submission audit.",
            startup,
        )
    return None, None


async def submission_ready(
    startups: str | list[str] | None = None,
) -> InsightResult:
    """Process explicit or all in-scope Dealum submissions."""
    if isinstance(startups, str):
        requested_startups = [startups]
    elif startups:
        requested_startups = list(dict.fromkeys(startups))
    else:
        requested_startups = None

    adapter = DealumAdapter()
    if not adapter.is_configured():
        raise ValueError(
            "Dealum is not configured. Set DEALUM_API_KEY and "
            "DEALUM_DEALROOM_ID."
        )
    run_id = _run_timestamp()
    try:
        applications = await _retry(
            "Dealum application discovery",
            adapter.list_applications,
        )
    except Exception as error:
        failure = SubmissionReadyResult(
            startup="Batch discovery",
            stage=None,
            status="failed after three attempts",
            error=str(error),
        )
        _save_failure_report([failure], run_id)
        raise RuntimeError(
            f"Submission-ready discovery failed: {error}"
        ) from error
    candidates, results = _resolve_candidates(
        applications,
        adapter,
        requested_startups,
    )
    check_config = load_repository_config("submission_ready")
    failures = [result for result in results if result.error]
    for match, stage in candidates:
        try:
            result = await _process_candidate(
                match,
                stage,
                applications=applications,
                adapter=adapter,
                force_refresh=requested_startups is not None,
                run_id=run_id,
                check_config=check_config,
            )
        except Exception as error:
            logger.exception(
                "[%s] submission_ready failed after retries",
                match.matched_name,
            )
            checklist_path, response_path = _latest_existing_artifacts(
                match.matched_name
            )
            result = SubmissionReadyResult(
                startup=match.matched_name,
                stage=stage,
                status="failed after three attempts",
                checklist_path=checklist_path,
                response_path=response_path,
                error=str(error),
            )
            failures.append(result)
        results.append(result)

    if failures:
        _save_failure_report(failures, run_id)
        details = "; ".join(
            f"{failure.startup}: {failure.error or failure.status}"
            for failure in failures
        )
        raise RuntimeError(
            f"Submission-ready failed for {len(failures)} startup(s): "
            + details
        )

    if not results:
        return []
    insights = [
        insight
        for result in results
        for insight in result.insights
    ]
    return insights

"""Draft feedback emails for open Dealum applications for the SICTIC screener."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.ai_text_generation import generate_markdown
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.startups.dealum import dealum_application_url
from lib.startups.dealum.session import dealum_session, list_applications
from lib.startups.dealum.stages import APPLICATION_STAGE, canonical_stage
from lib.storage import get_storage
from skills.submission_ready.submission_ready import (
    SEND_CONCERNS_ACTION,
    proposed_action,
    submission_ready,
)

logger = get_logger(__name__)

SKILL_NAME = "application_feedback"
# Generated dataset that holds the operations-only run summaries.
SUMMARY_DATASET = "application-feedback-runs"


@dataclass(frozen=True)
class ApplicationOutcome:
    """Result for one open application."""

    # Startup name as entered in Dealum.
    startup: str
    # Application code in Dealum, if any.
    code: str | None
    # Link to the application in Dealum, if known.
    dealum_url: str | None
    # Proposed action of the submission review; None when the review failed.
    action: str | None = None
    # Submission review report with the concerns.
    response: InsightFile | None = None
    # Drafted feedback email; only for applications with concerns.
    draft: InsightFile | None = None
    # True when the draft was written in this run, False when an earlier one was reused.
    draft_is_new: bool = False
    # Error text when the review or the draft failed.
    error: str | None = None


def _run_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _application_stage(application: dict[str, Any]) -> str | None:
    try:
        return canonical_stage(application.get("step"))
    except ValueError:
        logger.warning(
            "Skipping Dealum application %r with unknown stage %r",
            application.get("name"),
            application.get("step"),
        )
        return None


def open_applications(
    applications: list[dict[str, Any]],
    startups: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Select applications in the Dealum stage "Application", sorted by name.

    `startups` limits the selection to applications whose name or code matches.
    A requested startup without an open application raises.
    """
    selected = [
        application
        for application in applications
        if _application_stage(application) == APPLICATION_STAGE
    ]
    if startups:
        requested = {slugify(startup): startup for startup in startups}
        matched = set()
        filtered = []
        for application in selected:
            keys = {
                slugify(str(application.get(field) or ""))
                for field in ("name", "code")
            } & requested.keys()
            if keys:
                matched |= keys
                filtered.append(application)
        missing = [requested[key] for key in requested if key not in matched]
        if missing:
            raise ValueError(
                "No open Dealum application in the stage "
                f"{APPLICATION_STAGE!r} for: {', '.join(missing)}"
            )
        selected = filtered
    return sorted(
        selected,
        key=lambda application: str(application.get("name") or "").casefold(),
    )


def _review_insight(insights: InsightResult, identifier: str) -> InsightFile:
    for insight in insights:
        if insight.identifier == identifier:
            return insight
    raise RuntimeError(f"The submission review returned no {identifier} report.")


async def _draft_email(
    startup: str,
    checklist: InsightFile,
    response: InsightFile,
    instructions: str,
) -> tuple[InsightFile, bool]:
    """Draft the feedback email, reusing the stored draft while the review is unchanged.

    Returns the draft and whether it was written in this run.
    """
    checklist_report = checklist.content()
    response_report = response.content()
    draft = InsightFile(
        dataset=response.dataset,
        skill=SKILL_NAME,
        model=llm_model(),
        config_key=config_cache_key(
            instructions,
            {
                "startup": startup,
                "checklist": checklist_report,
                "response": response_report,
            },
        ),
    )
    if reusable := draft.find(selection="reusable"):
        logger.info("[%s] Using existing feedback draft %s", startup, reusable.path)
        return reusable, False

    prompt = (
        "### APPLICATION REVIEW START ###\n\n"
        f"{response_report}\n\n"
        "### APPLICATION REVIEW END ###\n\n"
        "### SUBMISSION CHECKLIST START ###\n\n"
        f"{checklist_report}\n\n"
        "### SUBMISSION CHECKLIST END ###\n\n"
        "### INSTRUCTIONS ###\n\n"
        + instructions.replace("{{startup}}", startup)
    )
    email = await generate_markdown(prompt)
    draft.save(email.strip() + "\n")
    logger.info("[%s] Feedback draft saved to %s", startup, draft.path)
    return draft, True


async def _process_application(
    application: dict[str, Any],
    dealroom_id: str,
    instructions: str,
) -> ApplicationOutcome:
    startup = str(application.get("name") or application.get("code") or "").strip()
    code = str(application.get("code") or "").strip() or None
    outcome = ApplicationOutcome(
        startup=startup,
        code=code,
        dealum_url=(
            dealum_application_url(dealroom_id, application.get("id"))
            if application.get("id")
            else None
        ),
    )
    try:
        # The application code selects exactly this application.
        insights = await submission_ready(code or startup)
        checklist = _review_insight(insights, "checklist")
        response = _review_insight(insights, "response")
        action = proposed_action(response.content())
        if action is None:
            raise RuntimeError(
                f"The submission review {response.path} has no proposed action."
            )
        draft, draft_is_new = None, False
        if action == SEND_CONCERNS_ACTION:
            draft, draft_is_new = await _draft_email(
                startup, checklist, response, instructions,
            )
        return replace(
            outcome,
            action=action,
            response=response,
            draft=draft,
            draft_is_new=draft_is_new,
        )
    except Exception as error:
        logger.exception("[%s] Application feedback failed", startup)
        return replace(outcome, error=str(error) or type(error).__name__)


def _application_label(outcome: ApplicationOutcome) -> str:
    return f"{outcome.startup} ({outcome.code})" if outcome.code else outcome.startup


def _summary_markdown(outcomes: list[ApplicationOutcome], run_id: str) -> str:
    new_drafts = [outcome for outcome in outcomes if outcome.draft and outcome.draft_is_new]
    unchanged_drafts = [
        outcome for outcome in outcomes if outcome.draft and not outcome.draft_is_new
    ]
    complete = [
        outcome
        for outcome in outcomes
        if outcome.error is None and outcome.draft is None
    ]
    failures = [outcome for outcome in outcomes if outcome.error is not None]
    lines = [
        "# Feedback drafts for open applications",
        "",
        f"Run: {run_id}",
        "",
        f"Open applications in the Dealum stage \"{APPLICATION_STAGE}\": "
        f"{len(outcomes)}. New or changed drafts: {len(new_drafts)}. "
        f"Unchanged drafts: {len(unchanged_drafts)}. Without concerns: "
        f"{len(complete)}. Failed: {len(failures)}.",
        "",
        "Nothing was sent to the startups. Proofread each new or changed "
        "draft, replace [Screener name] and paste it into the Dealum messages "
        "of the application.",
    ]
    if new_drafts:
        lines += ["", "## New or changed drafts"]
    for outcome in new_drafts:
        lines += [
            "",
            f"### {_application_label(outcome)}",
            "",
            f"- Dealum: {outcome.dealum_url or 'Unknown'}",
            f"- Draft file: {outcome.draft.path}",
            f"- Review: {outcome.response.path}",
            "",
            "---",
            "",
            outcome.draft.content().strip(),
            "",
            "---",
        ]
    if unchanged_drafts:
        lines += [
            "",
            "## Unchanged drafts",
            "",
            "The application has not changed since this draft was written in an "
            "earlier run.",
            "",
        ]
        lines += [
            f"- {_application_label(outcome)}: {outcome.dealum_url or 'Unknown'}. "
            f"Draft file: {outcome.draft.path}"
            for outcome in unchanged_drafts
        ]
    if complete:
        lines += ["", "## Without concerns", ""]
        lines += [
            f"- {_application_label(outcome)}: {outcome.action}. "
            f"Review: {outcome.response.path}"
            for outcome in complete
        ]
    if failures:
        lines += ["", "## Failed", ""]
        lines += [
            f"- {_application_label(outcome)}: {outcome.error}"
            for outcome in failures
        ]
    return "\n".join(lines) + "\n"


def _save_summary(markdown: str, run_id: str) -> InsightFile:
    storage = get_storage()
    location = dataset_location_for_domain(SUMMARY_DATASET, "generated")
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.insights_rel)
    summary = InsightFile(
        dataset=location.slug,
        skill=SKILL_NAME,
        model=llm_model(),
        identifier="summary",
        subdir=True,
        run_id=run_id,
        config_key="application_feedback summary",
    )
    summary.save(markdown)
    return summary


async def application_feedback(
    startups: list[str] | None = None,
) -> list[InsightFile]:
    """Review open Dealum applications and draft feedback emails for the screener.

    Returns the run summary followed by the drafts. Only reads from Dealum and
    sends nothing; the screener sends the proofread drafts.
    """
    adapter = DealumAdapter()
    if not adapter.is_configured():
        raise ValueError(
            "Dealum is not configured. Set DEALUM_API_KEY and DEALUM_DEALROOM_ID."
        )
    instructions = load_repository_config(SKILL_NAME, "email_instructions")
    run_id = _run_timestamp()
    # One shared application snapshot for the selection and every review.
    with dealum_session():
        selected = open_applications(list_applications(adapter), startups)
        logger.info("Open applications to review: %d", len(selected))
        outcomes = [
            await _process_application(application, adapter.dealroom_id, instructions)
            for application in selected
        ]

    summary = _save_summary(_summary_markdown(outcomes, run_id), run_id)
    logger.info("Application feedback summary saved to %s", summary.path)
    failures = [outcome for outcome in outcomes if outcome.error is not None]
    if failures:
        raise RuntimeError(
            f"Application feedback failed for {len(failures)} application(s); "
            f"see {summary.path}: "
            + "; ".join(f"{outcome.startup}: {outcome.error}" for outcome in failures)
        )
    return [summary, *(outcome.draft for outcome in outcomes if outcome.draft)]

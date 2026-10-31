"""Draft feedback emails for open Dealum applications for the SICTIC screener."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from html import escape
from typing import Any

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.ai_text_generation import Review, generate_markdown
from lib.infrastructure.configuration import (
    config_cache_key,
    get_env_var,
    load_repository_config,
)
from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.gmail import send_html_email
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.startups.dealum import dealum_application_url
from lib.startups.dealum.session import dealum_session, list_applications
from lib.startups.dealum.stages import APPLICATION_STAGE, canonical_stage
from lib.storage import get_storage
from skills.send_gmail.render_email import markdown_to_email
from skills.submission_ready.submission_ready import (
    SEND_CONCERNS_ACTION,
    proposed_action,
    stated_concerns,
    submission_ready,
)

logger = get_logger(__name__)

SKILL_NAME = "application_feedback"
# Generated dataset that holds the operations-only run summaries.
SUMMARY_DATASET = "application-feedback-runs"
# Environment variable with the comma-separated screener email addresses.
SCREENER_EMAILS_VARIABLE = "SCREENER_EMAILS"
# Environment variable with the name that signs the drafts.
SCREENER_SIGNATURE_VARIABLE = "SCREENER_SIGNATURE"
# Signature the screener replaces by hand when no name is configured.
PLACEHOLDER_SIGNATURE = "[Screener name]"


class EmailMode(StrEnum):
    """How the run delivers its summary to the screener."""

    # Send nothing.
    OFF = "off"
    # Save the finished email next to the summary instead of sending it.
    DRY_RUN = "dry-run"
    # Send the email through gws.
    SEND = "send"


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


def _concerns_block(eligibility: list[str], missing: list[str]) -> str:
    def numbered(items: list[str]) -> str:
        return "\n".join(
            f"{index}. {item}" for index, item in enumerate(items, start=1)
        ) or "None."

    return (
        "Eligibility concerns:\n"
        f"{numbered(eligibility)}\n\n"
        "Missing or inconsistent information:\n"
        f"{numbered(missing)}"
    )


def _screener_signature() -> str:
    signature = get_env_var(SCREENER_SIGNATURE_VARIABLE, required=False) or ""
    return " ".join(signature.split()) or PLACEHOLDER_SIGNATURE


def _draft_reviewer(
    concern_count: int,
    signature: str,
) -> Callable[[str], Review[str]]:
    """Check that a draft raises no more points than the review contains and is signed."""

    def review(output: str) -> Review[str]:
        email = output.strip()
        problems = []
        points = len(re.findall(r"^\s*\d+\.\s", email, flags=re.MULTILINE))
        if not 1 <= points <= concern_count:
            problems.append(
                f"The message must list between 1 and {concern_count} numbered "
                f"points, one per stated concern or merged concerns; it lists {points}. "
                "Raise only the stated concerns."
            )
        if signature not in email:
            problems.append(
                f'End with "Best regards," followed by "{signature}" and "SICTIC".'
            )
        return Review(email, tuple(problems))

    return review


async def _draft_email(
    startup: str,
    response: InsightFile,
    instructions: str,
    signature: str,
) -> tuple[InsightFile, bool]:
    """Draft the feedback email, reusing the stored draft while the concerns are unchanged.

    The model only receives the review's stated concerns, so the draft cannot
    raise points from elsewhere in the review. Returns the draft and whether it
    was written in this run.
    """
    eligibility, missing = stated_concerns(response.content())
    concern_count = len(eligibility) + len(missing)
    if not concern_count:
        raise RuntimeError(
            f"The submission review {response.path} proposes sending concerns "
            "but states none."
        )
    concerns = _concerns_block(eligibility, missing)
    draft = InsightFile(
        dataset=response.dataset,
        skill=SKILL_NAME,
        model=llm_model(),
        config_key=config_cache_key(
            instructions,
            {"startup": startup, "signature": signature, "concerns": concerns},
        ),
    )
    if reusable := draft.find(selection="reusable"):
        logger.info("[%s] Using existing feedback draft %s", startup, reusable.path)
        return reusable, False

    prompt = (
        "### CONCERNS START ###\n\n"
        f"{concerns}\n\n"
        "### CONCERNS END ###\n\n"
        "### INSTRUCTIONS ###\n\n"
        + instructions.replace("{{startup}}", startup).replace("{{signature}}", signature)
    )
    email = await generate_markdown(
        prompt, reviewer=_draft_reviewer(concern_count, signature),
    )
    draft.save(email.strip() + "\n")
    logger.info("[%s] Feedback draft saved to %s", startup, draft.path)
    return draft, True


async def _process_application(
    application: dict[str, Any],
    dealroom_id: str,
    instructions: str,
    signature: str,
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
        response = _review_insight(insights, "response")
        action = proposed_action(response.content())
        if action is None:
            raise RuntimeError(
                f"The submission review {response.path} has no proposed action."
            )
        draft, draft_is_new = None, False
        if action == SEND_CONCERNS_ACTION:
            draft, draft_is_new = await _draft_email(
                startup, response, instructions, signature,
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


def _dealum_link(outcome: ApplicationOutcome) -> str:
    if not outcome.dealum_url:
        return "Dealum link unknown"
    return f"[Open the application in Dealum]({outcome.dealum_url})"


def _copyable_text(text: str) -> list[str]:
    """Wrap text in a code block, so line breaks and numbering survive copying."""
    longest_backticks = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_backticks + 1)
    return [f"{fence}text", text, fence]


def _application_label(outcome: ApplicationOutcome) -> str:
    return f"{outcome.startup} ({outcome.code})" if outcome.code else outcome.startup


def _summary_markdown(
    outcomes: list[ApplicationOutcome],
    run_id: str,
    signature: str,
) -> str:
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
        "Nothing was sent to the startups. Proofread each new or changed draft"
        + (
            f", replace {PLACEHOLDER_SIGNATURE}"
            if signature == PLACEHOLDER_SIGNATURE
            else ""
        )
        + " and paste it into the Dealum messages of the application.",
    ]
    if new_drafts:
        lines += ["", "## New or changed drafts"]
    for outcome in new_drafts:
        lines += [
            "",
            f"### {_application_label(outcome)}",
            "",
            f"- {_dealum_link(outcome)}",
            f"- Draft file: {outcome.draft.path}",
            f"- Review: {outcome.response.path}",
            "",
            *_copyable_text(outcome.draft.content().strip()),
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
            f"- {_application_label(outcome)}: {_dealum_link(outcome)}. "
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


def _summary_insight(identifier: str, run_id: str, extension: str = "md") -> InsightFile:
    storage = get_storage()
    location = dataset_location_for_domain(SUMMARY_DATASET, "generated")
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.insights_rel)
    return InsightFile(
        dataset=location.slug,
        skill=SKILL_NAME,
        model=llm_model(),
        identifier=identifier,
        subdir=True,
        run_id=run_id,
        extension=extension,
        config_key=f"application_feedback {identifier}",
    )


def _screener_emails() -> list[str]:
    value = get_env_var(SCREENER_EMAILS_VARIABLE, required=False) or ""
    addresses = [address.strip() for address in value.split(",") if address.strip()]
    if not addresses:
        raise ValueError(
            f"Set {SCREENER_EMAILS_VARIABLE} in .env to the comma-separated "
            "screener email addresses."
        )
    return addresses


def _email_subject(outcomes: list[ApplicationOutcome]) -> str:
    new_drafts = sum(1 for outcome in outcomes if outcome.draft and outcome.draft_is_new)
    failures = sum(1 for outcome in outcomes if outcome.error is not None)
    return (
        "SICTIC feedback drafts for open applications: "
        f"{new_drafts} new or changed, {failures} failed"
    )


def _deliver_email(
    mode: EmailMode,
    recipients: list[str],
    outcomes: list[ApplicationOutcome],
    summary_markdown: str,
    run_id: str,
) -> InsightFile | None:
    """Send or preview the summary email. Returns the preview file of a dry run."""
    has_news = any(
        (outcome.draft and outcome.draft_is_new) or outcome.error is not None
        for outcome in outcomes
    )
    if mode == EmailMode.OFF:
        return None
    if not has_news:
        logger.info("No new or changed drafts and no failures; no email to the screener")
        return None
    subject = _email_subject(outcomes)
    html = markdown_to_email(summary_markdown)
    if mode == EmailMode.SEND:
        send_html_email(recipients, subject, html)
        logger.info("Summary emailed to %s", ", ".join(recipients))
        return None
    preview = _summary_insight("email-preview", run_id, extension="html")
    note = (
        "<p><strong>Dry run: this email was not sent.</strong><br>"
        f"To: {escape(', '.join(recipients))}<br>Subject: {escape(subject)}</p><hr>"
    )
    # Show the note at the top of the email body.
    body_start = re.search(r"<body[^>]*>", html)
    position = body_start.end() if body_start else 0
    preview.save(html[:position] + note + html[position:] + "\n")
    logger.info("Email preview saved to %s", preview.path)
    return preview


async def application_feedback(
    startups: list[str] | None = None,
    email: EmailMode | str = EmailMode.OFF,
) -> list[InsightFile]:
    """Review open Dealum applications and draft feedback emails for the screener.

    Returns the run summary, the email preview of a dry run, and the drafts.
    Only reads from Dealum. `email` decides whether the summary is emailed to
    the screener; an email is only sent when there are new or changed drafts
    or failures. The screener sends the proofread drafts to the startups.
    """
    email = EmailMode(email)
    adapter = DealumAdapter()
    if not adapter.is_configured():
        raise ValueError(
            "Dealum is not configured. Set DEALUM_API_KEY and DEALUM_DEALROOM_ID."
        )
    # Check the recipients before the long review run.
    recipients = _screener_emails() if email != EmailMode.OFF else []
    instructions = load_repository_config(SKILL_NAME, "email_instructions")
    signature = _screener_signature()
    run_id = _run_timestamp()
    # One shared application snapshot for the selection and every review.
    with dealum_session():
        selected = open_applications(list_applications(adapter), startups)
        logger.info("Open applications to review: %d", len(selected))
        outcomes = [
            await _process_application(
                application, adapter.dealroom_id, instructions, signature,
            )
            for application in selected
        ]

    summary_markdown = _summary_markdown(outcomes, run_id, signature)
    summary = _summary_insight("summary", run_id)
    summary.save(summary_markdown)
    logger.info("Application feedback summary saved to %s", summary.path)
    # Failures are news for the screener, so deliver the email before raising.
    preview, email_error = None, None
    try:
        preview = _deliver_email(email, recipients, outcomes, summary_markdown, run_id)
    except Exception as error:
        logger.exception("Emailing the application feedback summary failed")
        email_error = error
    failures = [outcome for outcome in outcomes if outcome.error is not None]
    if failures:
        message = (
            f"Application feedback failed for {len(failures)} application(s); "
            f"see {summary.path}: "
            + "; ".join(f"{outcome.startup}: {outcome.error}" for outcome in failures)
        )
        if email_error is not None:
            message += f"; emailing the summary also failed: {email_error}"
        raise RuntimeError(message) from email_error
    if email_error is not None:
        raise email_error
    return [
        summary,
        *([preview] if preview else []),
        *(outcome.draft for outcome in outcomes if outcome.draft),
    ]

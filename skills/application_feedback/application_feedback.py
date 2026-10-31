"""Draft feedback emails for open Dealum applications for the SICTIC screener."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
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
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.gmail import send_html_email
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.startups.dealum import dealum_application_url
from lib.startups.dealum.session import dealum_session, list_applications
from lib.startups.dealum.stages import APPLICATION_STAGE, canonical_stage
from lib.storage import get_storage
from skills.application_feedback.delivery import delivery_journal
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
    # Include the full draft: newly generated, or not yet delivered to these recipients.
    draft_needs_attention: bool = False
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

    The model receives only stated concerns to reduce unsupported additions.
    The formatting reviewer does not verify factual fidelity or completeness.
    Returns the draft and whether it was written in this run.
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
        draft, draft_needs_attention = None, False
        if action == SEND_CONCERNS_ACTION:
            draft, draft_needs_attention = await _draft_email(
                startup, response, instructions, signature,
            )
        return replace(
            outcome,
            action=action,
            response=response,
            draft=draft,
            draft_needs_attention=draft_needs_attention,
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
    new_drafts = [outcome for outcome in outcomes if outcome.draft and outcome.draft_needs_attention]
    unchanged_drafts = [
        outcome for outcome in outcomes if outcome.draft and not outcome.draft_needs_attention
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
        f"{len(outcomes)}. New, changed or undelivered drafts: {len(new_drafts)}. "
        f"Unchanged drafts: {len(unchanged_drafts)}. Without concerns: "
        f"{len(complete)}. Failed: {len(failures)}.",
        "",
        "Nothing was sent to the startups. Proofread each included draft"
        + (
            f", replace {PLACEHOLDER_SIGNATURE}"
            if signature == PLACEHOLDER_SIGNATURE
            else ""
        )
        + " and paste it into the Dealum messages of the application.",
    ]
    if new_drafts:
        lines += ["", "## New, changed or undelivered drafts"]
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
            "These drafts were reused; in email modes they have already been "
            "delivered to the configured recipients.",
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
    new_drafts = sum(1 for outcome in outcomes if outcome.draft and outcome.draft_needs_attention)
    failures = sum(1 for outcome in outcomes if outcome.error is not None)
    return (
        "SICTIC feedback drafts for open applications: "
        f"{new_drafts} new, changed or undelivered, {failures} failed"
    )


def _deliver_email(
    mode: EmailMode,
    recipients: list[str],
    outcomes: list[ApplicationOutcome],
    summary_markdown: str,
    run_id: str,
    *,
    entries: dict[str, dict[str, str]],
    save_delivery: Callable[[], None],
    summary_path: str,
) -> InsightFile | None:
    """Send or preview the summary email. Returns the preview file of a dry run."""
    has_news = any(
        (outcome.draft and outcome.draft_needs_attention) or outcome.error is not None
        for outcome in outcomes
    )
    if mode == EmailMode.OFF:
        return None
    if not has_news:
        logger.info("No new, changed or undelivered drafts and no failures; no email to the screener")
        return None
    subject = _email_subject(outcomes)
    html = markdown_to_email(summary_markdown)
    if mode == EmailMode.SEND:
        pending = {
            _delivery_key(outcome, recipients): {
                "status": "uncertain",
                "digest": _draft_digest(outcome),
                "summary": summary_path,
            }
            for outcome in outcomes
            if outcome.draft and outcome.draft_needs_attention
        }
        entries.update(pending)
        save_delivery()  # Write before sending: a crash must not trigger a duplicate.
        try:
            send_html_email(recipients, subject, html)
        except InfrastructureError as error:
            if error.kind == InfrastructureErrorKind.CONFIGURATION:
                # The shared sender reports this when the gws executable was
                # not found. No mail was attempted; a later run may try again.
                for key in pending:
                    entries.pop(key, None)
                save_delivery()
            raise
        for key in pending:
            entries[key]["status"] = "sent"
        save_delivery()
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
    the screener; an email is only sent when there are new, changed or undelivered
    drafts or failures. The screener sends the proofread drafts to the startups.
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

    location = dataset_location_for_domain(SUMMARY_DATASET, "generated")
    journal_path = f"{location.insights_rel}/email-delivery.json"
    with delivery_journal(journal_path) as (entries, save_delivery):
        if email != EmailMode.OFF:
            outcomes = _pending_deliveries(outcomes, recipients, entries, journal_path)
        return _finish_run(
            outcomes, run_id, signature, email, recipients, entries, save_delivery,
        )


def _delivery_key(outcome: ApplicationOutcome, recipients: list[str]) -> str:
    return config_cache_key(
        {"application": outcome.dealum_url or outcome.code or outcome.startup,
         "recipients": sorted({address.casefold() for address in recipients})},
    )


def _draft_digest(outcome: ApplicationOutcome) -> str:
    return sha256(outcome.draft.content().encode("utf-8")).hexdigest()


def _pending_deliveries(
    outcomes: list[ApplicationOutcome],
    recipients: list[str],
    entries: dict[str, dict[str, str]],
    journal_path: str,
) -> list[ApplicationOutcome]:
    updated = []
    for outcome in outcomes:
        if outcome.draft is None:
            updated.append(outcome)
            continue
        receipt = entries.get(_delivery_key(outcome, recipients), {})
        if receipt.get("status") == "uncertain":
            raise RuntimeError(
                f"Email delivery for {outcome.startup} is uncertain; check Sent mail "
                f"against {receipt['summary']} before resolving its entry in "
                f"{journal_path}. It will not be resent automatically."
            )
        updated.append(replace(
            outcome, draft_needs_attention=receipt.get("digest") != _draft_digest(outcome),
        ))
    return updated


def _finish_run(
    outcomes: list[ApplicationOutcome],
    run_id: str,
    signature: str,
    email: EmailMode,
    recipients: list[str],
    entries: dict[str, dict[str, str]],
    save_delivery: Callable[[], None],
) -> list[InsightFile]:
    summary_markdown = _summary_markdown(outcomes, run_id, signature)
    summary = _summary_insight("summary", run_id)
    summary.save(summary_markdown)
    logger.info("Application feedback summary saved to %s", summary.path)
    # Failures are news for the screener, so deliver the email before raising.
    preview, email_error = None, None
    try:
        preview = _deliver_email(
            email, recipients, outcomes, summary_markdown, run_id,
            entries=entries, save_delivery=save_delivery, summary_path=summary.path,
        )
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

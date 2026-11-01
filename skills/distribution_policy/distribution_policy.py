"""Deliver SICTIC insights by email according to two explicit rules.

- Screener feedback: after the nightly bulk refresh, email the summary of
  feedback drafts for open applications to the configured screeners.
- Requested insights: email an insight to the person who asked for it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import config_cache_key, get_env_var
from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.startups.dealum import DealumReconciliationError, reconcile_dealum_startup
from lib.startups.dealum.session import list_applications
from lib.startups.dealum.stages import APPLICATION_STAGE, canonical_stage
from lib.startups.identity import canonical_startup_slug
from lib.storage import get_storage
from skills.application_feedback.application_feedback import (
    PLACEHOLDER_SIGNATURE,
    feedback_state,
    screener_signature,
)
from skills.distribution_policy.delivery import delivery_journal
from skills.send_gmail.render_email import markdown_to_email
from skills.send_gmail.send_gmail import send_gmail
from skills.submission_ready.submission_ready import SEND_CONCERNS_ACTION

logger = get_logger(__name__)

SKILL_NAME = "distribution_policy"
# Generated dataset that holds the operations-only screener summaries.
SUMMARY_DATASET = "application-feedback-runs"
# Delivery receipts of the screener emails, in the summary dataset's insights.
JOURNAL_NAME = "email-delivery.json"
# Environment variable with the comma-separated screener email addresses.
SCREENER_EMAILS_VARIABLE = "SCREENER_EMAILS"


class EmailMode(StrEnum):
    """How the screener summary is delivered."""

    # Send nothing.
    OFF = "off"
    # Save the finished email next to the summary instead of sending it.
    DRY_RUN = "dry-run"
    # Send the email through send_gmail.
    SEND = "send"


@dataclass(frozen=True)
class OpenApplication:
    """Feedback state of one open application for the screener summary."""

    # Startup name as entered in Dealum.
    startup: str
    # Application code in Dealum, if any.
    code: str | None
    # Link to the application in Dealum, if known.
    dealum_url: str | None
    # Dataset slug of the startup's dossier.
    dataset_slug: str | None = None
    # Proposed action of the latest review; None when it could not be read.
    action: str | None = None
    # Latest submission review.
    response: InsightFile | None = None
    # Current feedback draft; only for applications with concerns.
    draft: InsightFile | None = None
    # Show the full draft: changed, or not yet delivered to these recipients.
    needs_attention: bool = False
    # Delivery to these recipients is uncertain; never resent automatically.
    delivery_uncertain: bool = False
    # Why the application is not ready, e.g. no review or no current draft yet.
    problem: str | None = None


def _run_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _stage(value: Any, startup: str) -> str | None:
    try:
        return canonical_stage(value)
    except ValueError:
        logger.warning("Skipping Dealum application %r with unknown stage %r", startup, value)
        return None


def open_applications(
    applications: list[dict[str, Any]],
    adapter: DealumAdapter,
) -> list[OpenApplication]:
    """Select startups whose latest Dealum application is in the stage "Application".

    The shared Dealum matching selects each startup's latest application, as
    bulk refresh does, so an older application cannot keep a startup open.
    """
    names = sorted(
        {
            str(application.get("name") or "").strip()
            for application in applications
            if str(application.get("name") or "").strip()
            and _stage(application.get("step"), str(application.get("name"))) == APPLICATION_STAGE
        },
        key=str.casefold,
    )
    entries: dict[str, OpenApplication] = {}
    for name in names:
        try:
            match = reconcile_dealum_startup(name, adapter=adapter, applications=applications)
        except DealumReconciliationError as error:
            entries.setdefault(
                canonical_startup_slug(name),
                OpenApplication(name, None, None, problem=str(error)),
            )
            continue
        if _stage(match.step, match.matched_name) != APPLICATION_STAGE:
            continue
        entries.setdefault(match.dataset_slug, OpenApplication(
            startup=match.matched_name,
            code=match.application_code,
            dealum_url=match.dealum_url,
            dataset_slug=match.dataset_slug,
        ))
    return list(entries.values())


def _with_feedback(entry: OpenApplication) -> OpenApplication:
    if entry.problem is not None:
        return entry
    try:
        state = feedback_state(entry.dataset_slug)
    except Exception as error:
        return replace(entry, problem=str(error) or type(error).__name__)
    entry = replace(entry, action=state.action, response=state.response, draft=state.draft)
    if state.action == SEND_CONCERNS_ACTION and state.draft is None:
        return replace(
            entry,
            problem="The review has concerns but no current draft; bulk refresh "
            "did not draft it.",
        )
    return entry


def _delivery_key(entry: OpenApplication, recipients: list[str]) -> str:
    return config_cache_key({
        "application": entry.dealum_url or entry.code or entry.startup,
        "recipients": sorted({address.casefold() for address in recipients}),
    })


def _draft_digest(entry: OpenApplication) -> str:
    return sha256(entry.draft.content().encode("utf-8")).hexdigest()


def _delivery_status(
    entries: list[OpenApplication],
    recipients: list[str],
    receipts: dict[str, dict[str, str]],
) -> list[OpenApplication]:
    """Mark drafts that are new to these recipients, and hold back uncertain ones."""
    updated = []
    for entry in entries:
        if entry.draft is None:
            updated.append(entry)
            continue
        receipt = receipts.get(_delivery_key(entry, recipients), {}) if recipients else {}
        if receipt.get("status") == "uncertain":
            updated.append(replace(entry, delivery_uncertain=True))
            continue
        updated.append(replace(
            entry, needs_attention=receipt.get("digest") != _draft_digest(entry),
        ))
    return updated


def _dealum_link(entry: OpenApplication) -> str:
    if not entry.dealum_url:
        return "Dealum link unknown"
    return f"[Open the application in Dealum]({entry.dealum_url})"


def _copyable_text(text: str) -> list[str]:
    """Wrap text in a code block, so line breaks and numbering survive copying."""
    longest_backticks = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_backticks + 1)
    return [f"{fence}text", text, fence]


def _label(entry: OpenApplication) -> str:
    return f"{entry.startup} ({entry.code})" if entry.code else entry.startup


def _summary_markdown(
    entries: list[OpenApplication],
    run_id: str,
    signature: str,
    journal_path: str,
) -> str:
    attention = [entry for entry in entries if entry.draft and entry.needs_attention]
    uncertain = [entry for entry in entries if entry.draft and entry.delivery_uncertain]
    unchanged = [
        entry for entry in entries
        if entry.draft and not entry.needs_attention and not entry.delivery_uncertain
    ]
    complete = [
        entry for entry in entries
        if entry.problem is None and entry.draft is None
    ]
    not_ready = [entry for entry in entries if entry.problem is not None]
    lines = [
        "# Feedback drafts for open applications",
        "",
        f"Run: {run_id}",
        "",
        f"Open applications in the Dealum stage \"{APPLICATION_STAGE}\": "
        f"{len(entries)}. New, changed or undelivered drafts: {len(attention)}. "
        f"Delivery uncertain: {len(uncertain)}. Unchanged drafts: {len(unchanged)}. "
        f"Without concerns: {len(complete)}. Not ready: {len(not_ready)}.",
        "",
        "Nothing was sent to the startups. Proofread each included draft"
        + (f", replace {PLACEHOLDER_SIGNATURE}" if signature == PLACEHOLDER_SIGNATURE else "")
        + " and paste it into the Dealum messages of the application.",
    ]
    if attention:
        lines += ["", "## New, changed or undelivered drafts"]
    for entry in attention:
        lines += [
            "",
            f"### {_label(entry)}",
            "",
            f"- {_dealum_link(entry)}",
            f"- Draft file: {entry.draft.path}",
            f"- Review: {entry.response.path}",
            "",
            *_copyable_text(entry.draft.content().strip()),
        ]
    if uncertain:
        lines += [
            "",
            "## Delivery uncertain",
            "",
            "An earlier email with these drafts may or may not have arrived, so "
            "they are not sent again automatically. Check the Sent folder of the "
            f"sender account, then set the entry in {journal_path} to `sent`, or "
            "remove it to have the draft included again.",
            "",
        ]
        lines += [
            f"- {_label(entry)}: {_dealum_link(entry)}. Draft file: {entry.draft.path}"
            for entry in uncertain
        ]
    if unchanged:
        lines += [
            "",
            "## Unchanged drafts",
            "",
            "These drafts were already delivered to the configured recipients.",
            "",
        ]
        lines += [
            f"- {_label(entry)}: {_dealum_link(entry)}. Draft file: {entry.draft.path}"
            for entry in unchanged
        ]
    if complete:
        lines += ["", "## Without concerns", ""]
        lines += [
            f"- {_label(entry)}: {entry.action}. Review: {entry.response.path}"
            for entry in complete
        ]
    if not_ready:
        lines += ["", "## Not ready", ""]
        lines += [f"- {_label(entry)}: {entry.problem}" for entry in not_ready]
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
        config_key=f"distribution_policy {identifier}",
    )


def _screener_emails(*, required: bool) -> list[str]:
    value = get_env_var(SCREENER_EMAILS_VARIABLE, required=False) or ""
    addresses = [address.strip() for address in value.split(",") if address.strip()]
    if required and not addresses:
        raise ValueError(
            f"Set {SCREENER_EMAILS_VARIABLE} in .env to the comma-separated "
            "screener email addresses."
        )
    return addresses


def _email_subject(entries: list[OpenApplication]) -> str:
    drafts = sum(1 for entry in entries if entry.draft and entry.needs_attention)
    not_ready = sum(1 for entry in entries if entry.problem is not None)
    return (
        "SICTIC feedback drafts for open applications: "
        f"{drafts} new, changed or undelivered, {not_ready} not ready"
    )


def _send_with_receipts(
    entries: list[OpenApplication],
    recipients: list[str],
    subject: str,
    summary_markdown: str,
    summary_path: str,
    receipts: dict[str, dict[str, str]],
    save_receipts: Callable[[], None],
) -> None:
    pending = {
        _delivery_key(entry, recipients): {
            "status": "uncertain",
            "digest": _draft_digest(entry),
            "summary": summary_path,
        }
        for entry in entries
        if entry.draft and entry.needs_attention
    }
    receipts.update(pending)
    save_receipts()  # Write before sending: a crash must not cause a second email.
    try:
        send_gmail(summary_markdown, recipients, subject)
    except InfrastructureError as error:
        if error.kind == InfrastructureErrorKind.CONFIGURATION:
            # The gws program was not found, so nothing was sent; retry later.
            for key in pending:
                receipts.pop(key, None)
            save_receipts()
        raise
    for key in pending:
        receipts[key]["status"] = "sent"
    save_receipts()
    logger.info("Screener summary emailed to %s", ", ".join(recipients))


def _save_preview(
    recipients: list[str],
    subject: str,
    summary_markdown: str,
    run_id: str,
) -> InsightFile:
    html = markdown_to_email(summary_markdown)
    note = (
        "<p><strong>Dry run: this email was not sent.</strong><br>"
        f"To: {escape(', '.join(recipients))}<br>Subject: {escape(subject)}</p><hr>"
    )
    # Show the note at the top of the email body.
    body_start = re.search(r"<body[^>]*>", html)
    position = body_start.end() if body_start else 0
    preview = _summary_insight("screener-email-preview", run_id, extension="html")
    preview.save(html[:position] + note + html[position:] + "\n")
    logger.info("Screener email preview saved to %s", preview.path)
    return preview


def screener_feedback(email: EmailMode | str = EmailMode.OFF) -> list[InsightFile]:
    """Summarize the feedback drafts of open applications for the screeners.

    Reads the current open applications from Dealum and their stored reviews
    and drafts, without generating anything; bulk refresh writes those first.
    `email` decides whether the summary is emailed to `SCREENER_EMAILS`. An
    email is only sent when there are new, changed or undelivered drafts, or
    applications that are not ready. Drafts whose earlier delivery is uncertain
    are listed but never resent automatically. Returns the summary and, for a
    dry run, the email preview.
    """
    email = EmailMode(email)
    adapter = DealumAdapter()
    if not adapter.is_configured():
        raise ValueError(
            "Dealum is not configured. Set DEALUM_API_KEY and DEALUM_DEALROOM_ID."
        )
    recipients = _screener_emails(required=email != EmailMode.OFF)
    signature = screener_signature()
    run_id = _run_timestamp()
    entries = [
        _with_feedback(entry)
        for entry in open_applications(list_applications(adapter), adapter)
    ]
    location = dataset_location_for_domain(SUMMARY_DATASET, "generated")
    journal_path = f"{location.insights_rel}/{JOURNAL_NAME}"
    with delivery_journal(journal_path) as (receipts, save_receipts):
        entries = _delivery_status(entries, recipients, receipts)
        summary_markdown = _summary_markdown(entries, run_id, signature, journal_path)
        summary = _summary_insight("screener-summary", run_id)
        summary.save(summary_markdown)
        logger.info("Screener summary saved to %s", summary.path)
        has_news = any(
            (entry.draft and entry.needs_attention) or entry.problem is not None
            for entry in entries
        )
        if email == EmailMode.OFF:
            return [summary]
        if not has_news:
            logger.info("No new, changed or undelivered drafts; no email to the screeners")
            return [summary]
        subject = _email_subject(entries)
        if email == EmailMode.DRY_RUN:
            return [summary, _save_preview(recipients, subject, summary_markdown, run_id)]
        _send_with_receipts(
            entries, recipients, subject, summary_markdown, summary.path,
            receipts, save_receipts,
        )
        return [summary]


def _read_insight(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        if not candidate.is_file():
            raise ValueError(f"Insight file not found: {path}")
        return candidate.read_text(encoding="utf-8")
    storage = get_storage()
    if not storage.exists(path):
        raise ValueError(f"Insight file not found in application storage: {path}")
    return storage.read_text(path)


def _insight_subject(path: str, markdown: str) -> str:
    title = next(
        (line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")),
        "",
    ) or Path(path).stem
    return f"SICTIC insight: {title}"


def requested_insights(
    insights: list[str],
    requester: str,
    *,
    requester_agreed: bool,
) -> None:
    """Email each requested insight in full to the person who asked for it.

    `insights` are Markdown files, as absolute paths or relative to the
    application storage. Send only what was requested, not the dependencies
    a workflow produced on the way. `requester_agreed` confirms that the
    requester asked for the email.
    """
    if not requester_agreed:
        raise ValueError("Email an insight only after the requester has agreed.")
    address = requester.strip()
    if "@" not in address or "," in address:
        raise ValueError("Requested insights go to exactly one requester address.")
    if not insights:
        raise ValueError("Name at least one requested insight file.")
    # Check every file before sending anything.
    for path in insights:
        if Path(path).suffix.lower() != ".md":
            raise ValueError(f"Only Markdown insights can be emailed: {path}")
    contents = [(path, _read_insight(path)) for path in insights]
    for path, markdown in contents:
        send_gmail(markdown, [address], _insight_subject(path, markdown))
        logger.info("Requested insight %s emailed to %s", path, address)

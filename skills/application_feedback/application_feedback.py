"""Screen one startup and email the screener the decision and any draft reply."""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from hashlib import sha256

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.ai_text_generation import Review, generate_markdown
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.configuration import (
    config_cache_key,
    get_env_var,
    load_repository_config,
)
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.startups.dealum.manifest import dealum_url_for_startup, read_manifest
from skills.application_feedback.delivery import delivery_journal
from skills.send_gmail.send_gmail import send_gmail
from skills.submission_ready.submission_ready import (
    SEND_CONCERNS_ACTION,
    proposed_action,
    stated_concerns,
    submission_ready,
)

logger = get_logger(__name__)

SKILL_NAME = "application_feedback"
# Environment variable with the name that signs the drafts.
SCREENER_SIGNATURE_VARIABLE = "SCREENER_SIGNATURE"
# Signature the screener replaces by hand when no name is configured.
PLACEHOLDER_SIGNATURE = "[Screener name]"


APPLICATION_FEEDBACK_RECIPIENTS_VARIABLE = "APPLICATION_FEEDBACK_RECIPIENTS"
# Preserve existing receipt identities and storage across the migration.
JOURNAL_DATASET = "application-feedback-runs"
# Send failures that happen before gws contacts Gmail: the gws program is
# missing or its login failed. Other failures may still have delivered the email.
NOT_SENT_ERROR_KINDS = frozenset({
    InfrastructureErrorKind.CONFIGURATION,
    InfrastructureErrorKind.AUTHENTICATION,
})


class EmailMode(StrEnum):
    OFF = "off"
    DRY_RUN = "dry-run"
    SEND = "send"


def screener_signature() -> str:
    """Return the configured screener name, or the placeholder to replace by hand."""
    signature = get_env_var(SCREENER_SIGNATURE_VARIABLE, required=False) or ""
    return " ".join(signature.split()) or PLACEHOLDER_SIGNATURE


def _startup_name(startup_slug: str) -> str:
    name = read_manifest(startup_slug).get("startup")
    return " ".join(str(name).split()) if name else startup_slug


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


def _review_concerns(response: InsightFile) -> tuple[str, int]:
    eligibility, missing = stated_concerns(response.content())
    concern_count = len(eligibility) + len(missing)
    if not concern_count:
        raise ValueError(
            f"The submission review {response.path} proposes sending concerns "
            "but states none."
        )
    return _concerns_block(eligibility, missing), concern_count


def _draft_insight(
    startup_slug: str,
    startup_name: str,
    concerns: str,
    instructions: str,
    signature: str,
) -> InsightFile:
    return InsightFile(
        dataset=startup_slug,
        skill=SKILL_NAME,
        model=llm_model(),
        config_key=config_cache_key(
            instructions,
            {"startup": startup_name, "signature": signature, "concerns": concerns},
        ),
    )


async def _draft_reply(
    startup_slug: str,
    startup_name: str,
    response: InsightFile,
    signature: str,
) -> InsightFile:
    """Draft the reply to the startup, reusing a stored or manual draft for unchanged inputs."""
    concerns, concern_count = _review_concerns(response)
    instructions = load_repository_config(SKILL_NAME, "email_instructions")
    draft = _draft_insight(startup_slug, startup_name, concerns, instructions, signature)
    if reusable := draft.find(selection="reusable"):
        logger.info("[%s] Using existing feedback draft %s", startup_slug, reusable.path)
        return reusable

    # The model only receives the stated concerns to reduce unsupported
    # additions. The reviewer checks the format, not factual fidelity.
    prompt = (
        "### CONCERNS START ###\n\n"
        f"{concerns}\n\n"
        "### CONCERNS END ###\n\n"
        "### INSTRUCTIONS ###\n\n"
        + instructions.replace("{{startup}}", startup_name).replace("{{signature}}", signature)
    )
    email = await generate_markdown(
        prompt, reviewer=_draft_reviewer(concern_count, signature),
    )
    draft.save(email.strip() + "\n")
    logger.info("[%s] Feedback draft saved to %s", startup_slug, draft.path)
    return draft


def _copyable_text(text: str) -> list[str]:
    """Wrap text in a code block, so line breaks and numbering survive copying."""
    longest_backticks = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_backticks + 1)
    return [f"{fence}text", text, fence]


def decision_email(
    startup_name: str,
    action: str,
    dealum_url: str | None,
    response: InsightFile,
    draft: InsightFile | None,
    signature: str,
) -> str:
    """Compose the screener email: proposed action first, then the review and any draft."""
    lines = [
        f"# {startup_name}: {action}",
        "",
        f"[Open the application in Dealum]({dealum_url})" if dealum_url else "Dealum link unknown.",
        "",
    ]
    if draft is None:
        lines += [
            "If you agree with the review below, carry out the proposed action in Dealum.",
            "",
        ]
    else:
        lines += [
            "If you agree with the review below, proofread the reply to the startup"
            + (f", replace {PLACEHOLDER_SIGNATURE}" if signature == PLACEHOLDER_SIGNATURE else "")
            + " and send it through the Dealum messages of the application.",
            "",
        ]
    # The review's own headings move one level down, below the email title.
    lines.append(re.sub(r"^#", "##", response.content().strip(), flags=re.MULTILINE))
    if draft is not None:
        lines += ["", "## Reply to the startup", "", *_copyable_text(draft.content().strip())]
    return "\n".join(lines) + "\n"


def _deliver_decision(
    startup_slug: str,
    startup_name: str,
    action: str,
    response: InsightFile,
    draft: InsightFile | None,
    signature: str,
) -> None:
    """Email the decision once per new or changed review and draft."""
    value = get_env_var(APPLICATION_FEEDBACK_RECIPIENTS_VARIABLE, required=False) or ""
    recipients = list(dict.fromkeys(
        address.strip() for address in value.split(",") if address.strip()
    ))
    if not recipients:
        logger.info("[%s] No %s configured; decision not emailed",
                    startup_slug, APPLICATION_FEEDBACK_RECIPIENTS_VARIABLE)
        return
    manifest = read_manifest(startup_slug)
    dealum_url = dealum_url_for_startup(startup_slug)
    key = config_cache_key({
        "application": dealum_url or manifest.get("code") or startup_name,
        "recipients": sorted({address.casefold() for address in recipients}),
    })
    content = decision_email(startup_name, action, dealum_url, response, draft, signature)
    # The digest covers the review and the draft, so a new or changed decision
    # is emailed once and an unchanged one stays quiet.
    digest = sha256(content.encode("utf-8")).hexdigest()
    location = dataset_location_for_domain(JOURNAL_DATASET, "generated")
    journal_path = f"{location.insights_rel}/email-delivery.json"
    with delivery_journal(journal_path) as (receipts, save_receipts):
        receipt = receipts.get(key, {})
        if receipt.get("status") == "uncertain":
            logger.warning("[%s] Prior delivery uncertain; inspect %s before resending",
                           startup_slug, journal_path)
            return
        if receipt.get("digest") == digest:
            logger.info("[%s] Unchanged screening decision already delivered", startup_slug)
            return
        # The legacy "summary" field records the main file of the email.
        receipts[key] = {
            "status": "uncertain",
            "digest": digest,
            "summary": (draft or response).path,
        }
        save_receipts()
        try:
            send_gmail(content, recipients, f"SICTIC screening: {startup_name}: {action}")
        except InfrastructureError as error:
            if error.kind in NOT_SENT_ERROR_KINDS:
                # Nothing was sent, so a later run sends this decision again.
                receipts.pop(key, None)
                save_receipts()
            raise
        receipts[key]["status"] = "sent"
        save_receipts()
        logger.info("[%s] Screening decision emailed to configured reviewers", startup_slug)


async def application_feedback(
    startup: str, *, email: EmailMode | str = EmailMode.SEND,
) -> list[InsightFile]:
    """Screen one startup and email the screener its decision and any draft reply.

    Calls submission_ready for the review. A review proposing "Send concerns to
    startup" also gets a draft reply. Returns the draft, or an empty list when
    there is no review or no concerns. Delivery to APPLICATION_FEEDBACK_RECIPIENTS
    is tracked separately from draft reuse.
    """
    email_mode = EmailMode(email)
    insights = await submission_ready(startup)
    response = next(
        (insight for insight in insights if insight.identifier == "response"), None,
    )
    if response is None:
        logger.info("[%s] No submission review; nothing to send", startup)
        return []
    startup_slug = response.dataset
    startup_name = _startup_name(startup_slug)
    action = proposed_action(response.content())
    if action is None:
        raise ValueError(f"The submission review {response.path} has no proposed action.")
    signature = screener_signature()
    draft = None
    if action == SEND_CONCERNS_ACTION:
        draft = await _draft_reply(startup_slug, startup_name, response, signature)
    else:
        logger.info("[%s] Review proposes %r; no draft reply", startup_slug, action)
    if email_mode == EmailMode.SEND:
        _deliver_decision(startup_slug, startup_name, action, response, draft, signature)
    return [draft] if draft else []

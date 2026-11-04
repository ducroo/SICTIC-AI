"""Draft and deliver feedback for one startup from a fresh submission review."""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from hashlib import sha256

from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location_for_domain, find_dataset_location
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
from lib.startups.identity import canonical_startup_slug
from skills.application_feedback.delivery import delivery_journal
from skills.send_gmail.send_gmail import send_gmail
from skills.submission_ready.submission_ready import (
    SEND_CONCERNS_ACTION,
    latest_response,
    proposed_action,
    stated_concerns,
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


def _latest_review(startup: str) -> tuple[str, str, InsightFile, str] | None:
    """Return a fresh review and its identity/action, or None when unavailable."""
    startup_slug = canonical_startup_slug(startup)
    response = latest_response(startup_slug, require_fresh=True)
    if response is None:
        logger.info("[%s] No fresh submission review; no feedback", startup_slug)
        return None
    action = proposed_action(response.content())
    if action is None:
        raise ValueError(f"The submission review {response.path} has no proposed action.")
    return startup_slug, _startup_name(startup_slug), response, action


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


def _deliver_draft(startup_slug: str, startup_name: str, draft: InsightFile) -> None:
    value = get_env_var(APPLICATION_FEEDBACK_RECIPIENTS_VARIABLE, required=False) or ""
    recipients = list(dict.fromkeys(
        address.strip() for address in value.split(",") if address.strip()
    ))
    if not recipients:
        logger.info("[%s] No %s configured; draft saved without email",
                    startup_slug, APPLICATION_FEEDBACK_RECIPIENTS_VARIABLE)
        return
    manifest = read_manifest(startup_slug)
    key = config_cache_key({
        "application": dealum_url_for_startup(startup_slug) or manifest.get("code") or startup_name,
        "recipients": sorted({address.casefold() for address in recipients}),
    })
    content = draft.content()
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
            logger.info("[%s] Unchanged feedback already delivered", startup_slug)
            return
        receipts[key] = {"status": "uncertain", "digest": digest, "summary": draft.path}
        save_receipts()
        try:
            send_gmail(content, recipients, f"SICTIC application feedback: {startup_name}")
        except InfrastructureError as error:
            if error.kind == InfrastructureErrorKind.CONFIGURATION:
                receipts.pop(key, None)
                save_receipts()
            raise
        receipts[key]["status"] = "sent"
        save_receipts()
        logger.info("[%s] Feedback emailed to configured reviewers", startup_slug)


async def application_feedback(
    startup: str, *, email: EmailMode | str = EmailMode.SEND,
) -> list[InsightFile]:
    """Draft and email feedback for one startup with a fresh stored review.

    Returns the full email as an InsightFile, including reused/manual drafts.
    Missing or stale reviews and reviews without concerns return an empty list.
    Delivery to APPLICATION_FEEDBACK_RECIPIENTS is tracked separately from
    draft reuse. Run submission_ready first; bulk refresh owns that dependency.
    """
    email_mode = EmailMode(email)
    startup_slug = canonical_startup_slug(startup)
    if find_dataset_location(startup_slug) is None or latest_response(startup_slug) is None:
        return []
    await sync_datasets([startup_slug], raise_on_error=True)
    state = _latest_review(startup_slug)
    if state is None:
        return []
    startup_slug, startup_name, response, action = state
    if action != SEND_CONCERNS_ACTION:
        logger.info("[%s] Review proposes %r; no feedback draft", startup_slug, action)
        return []
    concerns, concern_count = _review_concerns(response)
    instructions = load_repository_config(SKILL_NAME, "email_instructions")
    signature = screener_signature()
    draft = _draft_insight(startup_slug, startup_name, concerns, instructions, signature)
    if reusable := draft.find(selection="reusable"):
        logger.info("[%s] Using existing feedback draft %s", startup_slug, reusable.path)
        if email_mode == EmailMode.SEND:
            _deliver_draft(startup_slug, startup_name, reusable)
        return [reusable]

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
    if email_mode == EmailMode.SEND:
        _deliver_draft(startup_slug, startup_name, draft)
    return [draft]

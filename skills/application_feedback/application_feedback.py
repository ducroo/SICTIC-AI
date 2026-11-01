"""Draft the feedback email for one startup from its latest submission review."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from lib.infrastructure.ai_text_generation import Review, generate_markdown
from lib.infrastructure.configuration import (
    config_cache_key,
    get_env_var,
    load_repository_config,
)
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.startups.dealum.manifest import read_manifest
from lib.startups.identity import canonical_startup_slug
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


@dataclass(frozen=True)
class FeedbackState:
    """Stored review of one startup and the draft that belongs to it."""

    # Startup name from its latest Dealum application, or the dataset slug.
    startup: str
    # Latest submission review of the startup.
    response: InsightFile
    # Proposed action of that review.
    action: str
    # Draft for the review's concerns; None without concerns or before drafting.
    draft: InsightFile | None


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


def _latest_review(startup: str) -> tuple[str, str, InsightFile, str]:
    """Return the slug, display name, latest review and its proposed action."""
    startup_slug = canonical_startup_slug(startup)
    response = latest_response(startup_slug)
    if response is None:
        raise ValueError(
            f"No submission review found for '{startup_slug}'. "
            f"Run /submission_ready {startup_slug} first."
        )
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


def feedback_state(startup: str) -> FeedbackState:
    """Read the latest review and its current draft, without generating anything.

    `draft` is None when the review has no concerns, or when no stored or
    manual draft matches the review's concerns, instructions and signature.
    """
    startup_slug, startup_name, response, action = _latest_review(startup)
    draft = None
    if action == SEND_CONCERNS_ACTION:
        concerns, _concern_count = _review_concerns(response)
        draft = _draft_insight(
            startup_slug,
            startup_name,
            concerns,
            load_repository_config(SKILL_NAME, "email_instructions"),
            screener_signature(),
        ).find(selection="reusable")
    return FeedbackState(startup_name, response, action, draft)


async def application_feedback(startup: str) -> list[InsightFile]:
    """Draft the feedback email for one startup from its latest stored review.

    Returns the draft, or an empty list when the review proposes no concerns.
    Reuses a stored or manual draft while its inputs are unchanged. Run
    submission_ready first; bulk refresh does this through the registry.
    """
    startup_slug, startup_name, response, action = _latest_review(startup)
    if action != SEND_CONCERNS_ACTION:
        logger.info("[%s] Review proposes %r; no feedback draft", startup_slug, action)
        return []
    concerns, concern_count = _review_concerns(response)
    instructions = load_repository_config(SKILL_NAME, "email_instructions")
    signature = screener_signature()
    draft = _draft_insight(startup_slug, startup_name, concerns, instructions, signature)
    if reusable := draft.find(selection="reusable"):
        logger.info("[%s] Using existing feedback draft %s", startup_slug, reusable.path)
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
    return [draft]

"""Lender-side review of one convertible-loan term sheet.

Slice 0 of docs/cla-review-design.md: the public contract, the configuration
(inactive lender-angle rules, SECA reference term sheets) and the fixtures.
The workflow itself (identify, extract, assess, audit, conversion, report)
arrives with the following slices; calling the skill today fails clearly.
"""
from __future__ import annotations

from typing import Any

from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile

logger = get_logger(__name__)

SKILL_NAME = "cla_review"
RULE_FIELDS = ("value", "unit", "source", "status", "effective_date", "active")
APPROVED_STATUS = "approved"
NOT_IMPLEMENTED = (
    "cla_review is not implemented yet: slice 0 ships the contract, the "
    "lender-angle rules (all inactive until approved), the SECA reference "
    "term sheets and the fixture; see docs/cla-review-design.md, section 7."
)


def load_rules(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the lender-angle rule table; an active rule must be approved."""
    statuses = settings.get("rule_statuses")
    rules = settings.get("rules")
    if not isinstance(statuses, list) or APPROVED_STATUS not in statuses:
        raise ValueError(
            "cla_review.settings.rule_statuses must list the allowed statuses, "
            f"including {APPROVED_STATUS!r}."
        )
    if not isinstance(rules, dict) or not rules:
        raise ValueError("cla_review.settings.rules must be a non-empty object.")
    for name, rule in rules.items():
        if not isinstance(rule, dict):
            raise ValueError(f"cla_review rule {name!r} must be an object.")
        missing = [field for field in RULE_FIELDS if field not in rule]
        if missing:
            raise ValueError(f"cla_review rule {name!r} lacks {missing}.")
        if rule["status"] not in statuses:
            raise ValueError(
                f"cla_review rule {name!r} has unknown status {rule['status']!r}."
            )
        if not isinstance(rule["active"], bool):
            raise ValueError(f"cla_review rule {name!r}: active must be a boolean.")
        if rule["active"] and rule["status"] != APPROVED_STATUS:
            raise ValueError(
                f"cla_review rule {name!r} is active but its status is "
                f"{rule['status']!r}; only {APPROVED_STATUS!r} rules may be active."
            )
    return rules


def active_rules(rules: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The rules a report may judge with; every other rule is an open question at most."""
    return {name: rule for name, rule in rules.items() if rule["active"]}


def load_reference_term_sheets(config: dict[str, Any]) -> dict[str, str]:
    references = config.get("reference_term_sheets")
    if not isinstance(references, dict) or len(references) < 2:
        raise ValueError(
            "cla_review.reference_term_sheets requires the SECA short-form and "
            "long-form term sheets."
        )
    for key, content in references.items():
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"cla_review reference term sheet {key!r} is empty.")
    return references


async def cla_review(
    dataset_name: str,
    *,
    document: str | None = None,
    ticket: float | None = None,
    fresh: bool = False,
) -> list[InsightFile]:
    """Review one CLA term sheet of a startup from the lender's side.

    Returns the Markdown report as the only element; JSON intermediates stay
    under ``insights/cla-review/``. Not implemented before slice 1.
    """
    if ticket is not None and ticket <= 0:
        raise ValueError("--ticket must be a positive amount.")
    config = load_repository_config(SKILL_NAME)
    load_rules(config["settings"])
    load_reference_term_sheets(config)
    logger.info(
        "[%s] cla_review requested (document=%s, ticket=%s, fresh=%s)",
        dataset_name, document, ticket, fresh,
    )
    raise ValueError(NOT_IMPLEMENTED)

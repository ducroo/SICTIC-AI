from __future__ import annotations

import json

from lib.batch_audit import batch_audit
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import validate_audit_document
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import find_dataset_location
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model

logger = get_logger(__name__)

_INTRO = """# Pitch deck review

This checks the deck against the jury criteria and investment criteria SICTIC publishes for startups. Business potential, product innovation, team potential, and document quality come from the Investor Day assessment. The investment criteria are the published eligibility rules. The check reads the deck. It does not decide an invitation to pitch, and it does not submit an application.

Status meanings:

- Fine. The deck states this clearly.
- Sufficient. A reader can understand the point.
- Borderline. The point is incomplete.
- Critical. The deck states something that conflicts with a published criterion.
- Not Found. The deck does not address this.
"""


def _report(table: str) -> str:
    return f"{_INTRO}\n{table.strip()}\n"


async def pitch_deck_review(dataset_name: str) -> InsightResult:
    """Assess the pitch deck in a dataset and save one Markdown report."""
    location = find_dataset_location(dataset_name)
    if location is None:
        raise FileNotFoundError(
            f"Dataset {dataset_name!r} was not found. Put the pitch deck in a dataset first."
        )
    dataset_slug = location.slug
    await sync_datasets([dataset_slug], raise_on_error=True)
    review_config = load_repository_config("pitch_deck_review")
    output = InsightFile(
        dataset=dataset_slug,
        skill="pitch_deck_review",
        model=llm_model(),
        config_key=config_cache_key(
            review_config,
            load_repository_config("structured_output"),
        ),
    )
    reusable = output.find(selection="reusable")
    if reusable is not None:
        return [reusable]

    audit_insight = await batch_audit(
        dataset_name=dataset_slug,
        checklist_markdown=review_config["checklist"],
        skill_name="pitch_deck_review",
        llm_instructions=review_config["audit_instructions"],
        response_schema=review_config["audit_response_schema"],
    )
    validate_audit_document(json.loads(audit_insight.content()), require_complete=True)
    output.save(_report(json_to_markdown_table(audit_insight)))
    logger.info("Saved pitch deck review for %s at %s", dataset_slug, output.path)
    return [output]

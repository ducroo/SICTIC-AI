from __future__ import annotations

from lib.datasets.paths import find_dataset_location
from lib.infrastructure.logging import get_logger
from lib.insights import InsightResult
from skills.dd_checks.dd_checks import assess_dd_dataset

logger = get_logger(__name__)

_INTRO = """# Data-room review

This checks an uploaded data room against the document topics in SICTIC's published due diligence checklist (Business and Product Overview, Company, Team, Financial Situation, Customers, Intellectual Property / Data Protection / Security, and Software Development and Production). The assessment uses SICTIC's operational chapter checklists, which expand those topics and select product-type variants when the dossier supports it.

Status meanings follow the shared due-diligence audit:

- Fine / Sufficient / Borderline / Critical describe how the available documents answer each check.
- Not Found means the dossier does not address the check.

This is a document check. It is not an investment decision.
"""


async def dataroom_review(dataset_name: str) -> InsightResult:
    """Assess data-room documents in a dataset and save one Markdown report."""
    location = find_dataset_location(dataset_name)
    if location is None:
        raise FileNotFoundError(
            f"Dataset {dataset_name!r} was not found. Upload the data room first."
        )
    insights = await assess_dd_dataset(
        location.slug,
        display_name=dataset_name,
        skill_name="dataroom_review",
        report_title="Data-room review",
        report_preamble=_INTRO,
    )
    report = insights[0]
    cleaned = "\n".join(
        line
        for line in report.content().splitlines()
        if not line.startswith("**Model:**")
    ) + "\n"
    if cleaned != report.content():
        report.save(cleaned)
    logger.info("Saved data-room review for %s at %s", location.slug, report.path)
    return [report]

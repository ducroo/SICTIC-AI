from lib.insights import InsightFile, InsightResult
from lib.infrastructure.logging import get_logger
from lib.model_config import llm_model
from lib.startups.identity import canonical_startup_slug
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.ai_text_generation import generate_markdown

logger = get_logger(__name__)


def _find_dd_checks_report(startup_slug: str) -> InsightFile:
    try:
        report = InsightFile(
            dataset=startup_slug,
            skill="dd_checks",
            model=llm_model(),
        ).find(selection="any")
    except FileNotFoundError:
        report = None
    if report is None:
        raise ValueError(
            f"No dd_checks report found for '{startup_slug}'. "
            f"Run /dd_checks {startup_slug} first."
        )
    return report


async def dd_priorities(startup: str) -> InsightResult:
    """Synthesize up to eight priorities from a saved dd_checks report."""
    startup_slug = canonical_startup_slug(startup)
    source_insight = _find_dd_checks_report(startup_slug)
    source_report = source_insight.content()
    if not source_report.strip():
        raise ValueError(
            f"The dd_checks report for '{startup_slug}' is empty. "
            f"Run /dd_checks {startup_slug} again."
        )

    config = load_repository_config("dd_priorities")
    instructions = config["llm_instructions"].replace(
        "{{startup}}",
        startup,
    )
    config_key = f"{instructions}\n\n{source_report}"
    output_insight = InsightFile(
        dataset=startup_slug,
        skill="dd_priorities",
        model=llm_model(),
        config_key=config_key,
    )
    reusable = output_insight.find(selection="reusable")
    if reusable:
        logger.info(
            "[%s] Using cached DD priorities from %s",
            startup_slug,
            reusable.path,
        )
        return [reusable]

    prompt = (
        "### DD_CHECKS REPORT START ###\n\n"
        f"{source_report}\n\n"
        "### DD_CHECKS REPORT END ###\n\n"
        "### INSTRUCTIONS ###\n\n"
        f"{instructions}"
    )
    result = await generate_markdown(prompt)

    output_insight.save(result)
    logger.info("[%s] DD priorities saved to %s", startup_slug, output_insight.path)
    return [output_insight]

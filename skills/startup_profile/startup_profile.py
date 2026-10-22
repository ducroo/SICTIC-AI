from lib.model_config import llm_model
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.datasets.paths import find_dataset_location
from lib.insights import INSUFFICIENT_CONTEXT, InsightFile, InsightResult
from skills.startup_sector import startup_sector_as_dict
from lib.slugify import slugify
from lib.infrastructure.logging import get_logger
from lib.datasets.ingestion import sync_datasets

logger = get_logger(__name__)


def _classification_bullet(classification: dict) -> str:
    """Render validated classification data as the fifth profile bullet."""
    if "sector" in classification:
        return (
            "- **Classification:**\n"
            f"  - **SICTIC sector:** {classification['sector']}\n"
            "  - **Technologies:** Not available from the legacy SICTIC classification."
        )

    lines = ["- **Classification:**"]
    for component, primary_label, secondary_label in (
        ("industries", "Primary-industry", "Secondary-industries"),
        ("technologies", "Primary-technology", "Secondary-technologies"),
    ):
        selection = classification["result"]["classifications"][component]
        names = classification["category_names"][component]
        primary = names[selection["primary"]] if selection["primary"] else "Insufficient evidence"
        secondary = ", ".join(names[identifier] for identifier in selection["secondary"]) or "None selected"
        lines.extend((
            f"  - **{primary_label}:** {primary}.",
            f"  - **{secondary_label}:** {secondary}.",
        ))
    return "\n".join(lines)


async def startup_profile(startup: str) -> InsightResult:
    """Generate a startup diagnostic from a named dossier, including temporary ones."""
    startup_slug = slugify(startup)
    from lib.startups.sources import ensure_startup_dataset

    location = find_dataset_location(startup_slug)
    if location is None or location.domain != "generated":
        status = await ensure_startup_dataset(startup_slug)
        startup_slug = status.dataset_slug
    await sync_datasets([startup_slug], raise_on_error=True)
    default_llm = llm_model()

    config = load_repository_config("startup_profile")
    query = config['query']
    llm_instructions = config['llm_instructions']
    questions = [line.strip() for line in query.splitlines() if line.strip()]

    insight = InsightFile(
        dataset=startup_slug,
        skill="startup_profile",
        model=default_llm,
        config_key=config_cache_key(config),
    )
    preferred = insight.find(selection="any")
    if preferred is not None and preferred.model == "manual":
        return [preferred]

    classification = await startup_sector_as_dict(startup_slug)
    classification_bullet = _classification_bullet(classification)
    insight.config_key = config_cache_key(config, classification, classification_bullet)
    reusable = insight.find(selection="reusable")
    if reusable:
        return [reusable]

    profile_output = await dataset_chat(
        dataset_name=startup_slug,
        queries=questions,
        prompt=(
            f"Query: {'\n\n'.join(questions)}\n\n"
            f"Instructions: {llm_instructions}"
        ),
    )

    if not profile_output or not profile_output.strip():
        raise ValueError("LLM returned an empty response for the profile output.")
    if profile_output.strip() != INSUFFICIENT_CONTEXT:
        profile_output = f"{profile_output.rstrip()}\n\n{classification_bullet}\n"
    insight.save(profile_output)
    return [insight]

from typing import Optional

from lib.logger import get_logger
from skills.config_load.config_load import config_load
from skills.dataset_chat.core.ingestion import sync_datasets

from skills.person_profile.person_profile import person_profile
from skills.investor_profile.investor_profile import investor_profile
from skills.startup_profile.startup_profile import startup_profile
from skills.team_profile.team_profile import team_profile
from skills.startup_traction.startup_traction import startup_traction
from skills.dd_checks.dd_checks import dd_checks
from skills.expert_search.expert_search import expert_search
from skills.potential_investors.potential_investors import potential_investors
from skills.suggested_startups.suggested_startups import suggested_startups
from skills.person_profile.persons_in_dataset import persons_in_dataset

from lib.slugify import slugify
from lib.active_dataset import is_active_dataset
from lib.storage_domains import dataset_location, list_dataset_names

logger = get_logger(__name__)


async def _refresh_persons_in_dataset(dataset_name: str):
    import asyncio

    return await asyncio.to_thread(persons_in_dataset, dataset_name)


SKILL_MAP = {
    "startup-profile": {
        "func": startup_profile,
        "domains": ["startups"], "depends_on": []
    },
    "persons-in-dataset": {
        "func": _refresh_persons_in_dataset,
        "domains": ["startups", "community"],
        "depends_on": [],
    },
    "person-profile": {
        "func": person_profile,
        "domains": ["startups", "community"],
        "depends_on": ["persons-in-dataset"],
    },
    "team-profile": {
        "func": team_profile,
        "domains": ["startups"],
        "depends_on": ["startup-profile","person-profile"]
    },
    "startup-traction": {
        "func": startup_traction,
        "domains": ["startups"],
        "depends_on": ["startup-profile"]
    },
    "dd-checks": {
        "func": dd_checks,
        "domains": ["startups"],
        "depends_on": ["startup-profile"]
    },
    "investor-profile": {
        "func": investor_profile,
        "domains": ["community"],
        "depends_on": ["person-profile"]
    },
    "expert-search": {
        "func": expert_search,
        "domains": ["startups"],
        "depends_on": ["startup-profile", "investor-profile"]
    },
    "potential-investors": {
        "func": potential_investors,
        "domains": ["startups"],
        "depends_on": ["startup-profile", "investor-profile"]
    },
    "suggested-startups": {
        "func": suggested_startups,
        "domains": ["community"],
        "depends_on": ["startup-profile", "investor-profile"]
    }
}


def _expand_skill_dependencies(target_skills: list[str]) -> list[str]:
    expanded = set()

    def add_with_dependencies(skill_name: str) -> None:
        if skill_name not in SKILL_MAP:
            raise ValueError(f"Unknown bulk refresh skill: {skill_name}")
        if skill_name in expanded:
            return
        for dependency in SKILL_MAP[skill_name].get("depends_on", []):
            add_with_dependencies(dependency)
        expanded.add(skill_name)

    for skill_name in target_skills:
        add_with_dependencies(skill_name)
    return [skill_name for skill_name in SKILL_MAP if skill_name in expanded]


def _is_insight_derived_dataset(dataset_name: str) -> bool:
    dataset_slug = slugify(dataset_name)
    for skill_name in SKILL_MAP:
        skill_slug = slugify(skill_name)
        if (
            dataset_slug == skill_slug
            or dataset_slug == f"active-{skill_slug}"
            or dataset_slug.endswith(f"-{skill_slug}")
        ):
            return True
    return False


async def bulk_refresh(target_dataset: Optional[str] = None, target_skill: Optional[str] = None):
    """
    Refreshes core insights. Performs synchronous dataset ingestion first to prevent memory exhaustion,
    followed by parallelized LLM skill execution based on the target domains.
    """
    import asyncio

    target_skills = [slugify(s) for s in target_skill.split(",")] if target_skill else []
    target_skills = _expand_skill_dependencies(target_skills) if target_skills else []
    target_datasets = [slugify(d) for d in target_dataset.split(",")] if target_dataset else []
    skipped_derived = [
        dataset_name
        for dataset_name in target_datasets
        if _is_insight_derived_dataset(dataset_name)
    ]
    if skipped_derived:
        logger.info(
            "Skipping insight-derived datasets: "
            + ", ".join(skipped_derived)
        )
    target_datasets = [
        dataset_name
        for dataset_name in target_datasets
        if not _is_insight_derived_dataset(dataset_name)
    ]

    logger.info(f"Starting bulk refresh routine (skills={target_skills}, datasets={target_datasets})...")

    if target_datasets:
        all_datasets = target_datasets
        dataset_domains = {
            dataset_slug: dataset_location(dataset_slug).domain
            for dataset_slug in target_datasets
        }
    else:
        config = config_load()
        bulk_config = config["bulk_refresh"]

        # Extract string values from .md files and split by comma or newline
        ignore_raw = bulk_config["ignore_datasets"]

        ignore_datasets = [slugify(s) for s in ignore_raw.replace(',', '\n').split('\n') if slugify(s)]
        ignore_datasets.extend(slugify(k) for k in SKILL_MAP.keys())

        # Discover datasets from configured storage domains.
        all_datasets = []
        dataset_domains = {}
        for domain_name in ("startups", "community"):
            for item in list_dataset_names(domain_name):
                item_slug = slugify(item)
                if item_slug in ignore_datasets or _is_insight_derived_dataset(item_slug):
                    continue
                
                if not is_active_dataset(item_slug):
                    continue
                    
                all_datasets.append(item_slug)
                dataset_domains[item_slug] = domain_name

    if not all_datasets:
        logger.warning("No valid datasets found to process.")
        return

    from lib.startup_data_sources import ensure_startup_dataset

    resolved_datasets = []
    resolved_domains = {}
    for dataset_name in list(all_datasets):
        if dataset_domains.get(dataset_name) == "startups":
            status = await ensure_startup_dataset(dataset_name, sync_after_import=False)
            resolved_slug = status.dataset_slug
            resolved_datasets.append(resolved_slug)
            resolved_domains[resolved_slug] = "startups"
        else:
            resolved_datasets.append(dataset_name)
            resolved_domains[dataset_name] = dataset_domains[dataset_name]
    all_datasets = list(dict.fromkeys(resolved_datasets))
    dataset_domains = resolved_domains

    logger.info(f"Discovered {len(all_datasets)} datasets matching targets. Starting synchronous pre-ingestion...")

    # 1. Synchronous Pre-Ingestion
    # This runs sequentially over each dataset, using a fixed concurrency limit (10) for Docling tasks internally.
    await sync_datasets(all_datasets)
    logger.info("Pre-ingestion complete. Commencing LLM skill executions.")

    # 2. Dynamic DAG Execution
    completed_skills = set()
    skills_to_run = set(target_skills) if target_skills else set(SKILL_MAP.keys())
    
    # We loop until all requested skills are completed
    batch_index = 1
    while skills_to_run:
        # Find skills whose dependencies are fully met
        current_batch = []
        for skill_name in SKILL_MAP:
            if skill_name not in skills_to_run:
                continue
            deps = SKILL_MAP[skill_name].get("depends_on", [])
            # A dependency is met if it's already completed OR if it wasn't even requested
            # Actually, standard DAG behavior: we only care if the dependencies that are *also* being run are met.
            # But let's assume we require the dependency to be run if requested, or if not requested, we assume it's already available in cache.
            pending_deps = [d for d in deps if d in skills_to_run]
            if not pending_deps:
                current_batch.append(skill_name)
                
        if not current_batch:
            logger.error("Circular dependency or unresolvable skill tree detected! Aborting.")
            break
            
        logger.info(f"--- Starting Skill Batch {batch_index} ({', '.join(current_batch)}) ---")
        
        for skill_name in current_batch:
            skill_meta = SKILL_MAP[skill_name]
            allowed_domains = skill_meta["domains"]
            func = skill_meta["func"]
            
            tasks = []
            for dataset_name in all_datasets:
                dataset_slug = slugify(dataset_name)
                domain = dataset_domains[dataset_slug]
                
                if domain in allowed_domains:
                    logger.info(f"[{dataset_name}] Queueing {skill_name}...")
                    tasks.append(func(dataset_name))
                    
            if tasks:
                logger.info(f"Executing {len(tasks)} parallel tasks for {skill_name}...")
                await asyncio.gather(*tasks)
                
            skills_to_run.remove(skill_name)
            completed_skills.add(skill_name)
            
        batch_index += 1

    logger.info("Bulk refresh routine complete.")

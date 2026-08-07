from typing import Optional

from lib.logger import get_logger
from skills.config_load.config_load import config_load
from lib.datasets.ingestion import sync_datasets
from skills.skill_registry import SKILL_REGISTRY, expand_skill_dependencies

from lib.slugify import slugify
from lib.datasets.paths import dataset_location, list_all_dataset_names
from lib.datasets.state import is_active_dataset

logger = get_logger(__name__)


async def bulk_refresh(
    target_dataset: Optional[str] = None,
    target_skill: Optional[str] = None,
) -> None:
    """
    Refreshes core insights. Performs synchronous dataset ingestion first to prevent memory exhaustion,
    followed by parallelized LLM skill execution based on the target domains.
    """
    import asyncio

    target_skills = [slugify(s) for s in target_skill.split(",")] if target_skill else []
    target_skills = expand_skill_dependencies(target_skills) if target_skills else []
    target_datasets = [slugify(d) for d in target_dataset.split(",")] if target_dataset else []

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
        ignore_datasets.extend(slugify(k) for k in SKILL_REGISTRY)

        # Discover datasets from configured storage domains.
        all_datasets = []
        dataset_domains = {}
        for item in list_all_dataset_names():
            item_slug = slugify(item)
            if item_slug in ignore_datasets:
                continue
            if not is_active_dataset(item_slug):
                continue
            location = dataset_location(item_slug)
            all_datasets.append(item_slug)
            dataset_domains[item_slug] = location.domain

    if not all_datasets:
        logger.warning("No valid datasets found to process.")
        return

    from lib.startups.sources import ensure_startup_dataset

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
    skills_to_run = set(target_skills) if target_skills else set(SKILL_REGISTRY)
    
    # We loop until all requested skills are completed
    batch_index = 1
    while skills_to_run:
        # Find skills whose dependencies are fully met
        current_batch = []
        for skill_name in SKILL_REGISTRY:
            if skill_name not in skills_to_run:
                continue
            deps = SKILL_REGISTRY[skill_name].depends_on
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
            skill_meta = SKILL_REGISTRY[skill_name]
            allowed_domains = skill_meta.domains
            func = skill_meta.func
            
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

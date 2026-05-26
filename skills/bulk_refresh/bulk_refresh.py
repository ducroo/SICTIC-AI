from typing import Optional

from lib.logger import get_logger
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.dataset_chat.core.ingestion import sync_datasets

from skills.person_profile.person_profile import person_profile
from skills.investor_appetite.investor_appetite import investor_appetite
from skills.startup_profile.startup_profile import startup_profile
from skills.team_profile.team_profile import team_profile
from skills.startup_traction.startup_traction import startup_traction
from skills.dd_checks.dd_checks import dd_checks
from skills.expert_search.expert_search import expert_search
from skills.potential_investors.potential_investors import potential_investors
from skills.suggested_startups.suggested_startups import suggested_startups

from lib.slugify import slugify
from lib.active_dataset import is_active_dataset

logger = get_logger(__name__)

SKILL_MAP = {
    "person-profile": {"func": person_profile, "domains": ["startups", "community"], "depends_on": []},
    "startup-profile": {"func": startup_profile, "domains": ["startups"], "depends_on": []},

    "investor-appetite": {"func": investor_appetite, "domains": ["community"], "depends_on": ["person-profile"]},
    "team-profile": {"func": team_profile, "domains": ["startups"], "depends_on": ["startup-profile"]},
    "startup-traction": {"func": startup_traction, "domains": ["startups"], "depends_on": ["startup-profile"]},
    "dd-checks": {"func": dd_checks, "domains": ["startups"], "depends_on": ["startup-profile"]},

    "expert-search": {"func": expert_search, "domains": ["startups"], "depends_on": ["startup-profile", "person-profile"]},
    "potential-investors": {"func": potential_investors, "domains": ["startups"], "depends_on": ["startup-profile", "investor-appetite"]},

    "suggested-startups": {"func": suggested_startups, "domains": ["community"], "depends_on": ["startup-profile", "person-profile"]}
}

async def bulk_refresh(target_dataset: Optional[str] = None, target_skill: Optional[str] = None):
    """
    Refreshes core insights. Performs synchronous dataset ingestion first to prevent memory exhaustion,
    followed by parallelized LLM skill execution based on the target domains.
    """
    import asyncio

    target_skills = [slugify(s) for s in target_skill.split(",")] if target_skill else []
    target_datasets = [slugify(d) for d in target_dataset.split(",")] if target_dataset else []

    logger.info(f"Starting bulk refresh routine (skills={target_skills}, datasets={target_datasets})...")

    config = config_load()
    bulk_config = config["bulk_refresh"]

    # Extract string values from .md files and split by comma or newline
    community_raw = bulk_config["community_datasets"]
    ignore_raw = bulk_config["ignore_datasets"]

    community_datasets = [slugify(s) for s in community_raw.replace(',', '\n').split('\n') if slugify(s)]
    ignore_datasets = [slugify(s) for s in ignore_raw.replace(',', '\n').split('\n') if slugify(s)]
    ignore_datasets.extend(slugify(k) for k in SKILL_MAP.keys())

    storage = get_storage()

    # Discover Datasets — every direct child of `datasets/` is treated as a dataset folder.
    all_datasets = []
    if storage.exists("datasets"):
        for item in storage.list("datasets"):
            item_slug = slugify(item)
            if not storage.is_dir(f"datasets/{item}"):
                continue
            if item_slug in ignore_datasets:
                continue
            
            # Active dataset logic
            is_explicit = item_slug in target_datasets
            is_active = is_active_dataset(item_slug)
            
            # Skip if target_datasets is provided but this dataset is not in it
            if target_datasets and not is_explicit:
                continue
                
            # Skip if it wasn't explicitly requested AND doesn't have the active marker
            if not target_datasets and not is_active:
                continue
                
            all_datasets.append(item)

    if not all_datasets:
        logger.warning("No valid datasets found to process.")
        return

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
        for skill_name in list(skills_to_run):
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
                domain = "community" if dataset_slug in community_datasets else "startups"
                
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

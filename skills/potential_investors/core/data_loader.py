import os
from typing import List, Tuple
from skills.utils.logger import get_logger
from skills.utils.env import get_env_var
from skills.utils.adapters.linkedin import LinkedInAdapter
from skills.utils.slugify import slugify
from skills.investor_appetite.investor_appetite import investor_appetite

logger = get_logger(__name__)

async def fetch_data(startup_name: str, safe_llm_name: str, target_investors: list = None, exclude_investors: list = None) -> Tuple[str, List[str]]:
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    startup_name_lower = startup_name.lower()
    
    # Fetch startup profile
    raw_startup_filename = f"{startup_name_lower}-profile-{safe_llm_name}"
    startup_profile_path = os.path.join(gdrive_mount, "insights", startup_name_lower, f"{slugify(raw_startup_filename)}.md")
    profile_content = None
    
    if not os.path.exists(startup_profile_path):
        insights_dir = os.path.join(gdrive_mount, "insights", startup_name_lower)
        if os.path.exists(insights_dir):
            for f in os.listdir(insights_dir):
                if ("-profile-" in f or "_profile_" in f) and f.endswith(".md"):
                    if "team_profile" in f: continue
                    with open(os.path.join(insights_dir, f), 'r', encoding='utf-8') as file:
                        profile_content = file.read()
                    break
    else:
        with open(startup_profile_path, 'r', encoding='utf-8') as file:
            profile_content = file.read()
            
    if not profile_content:
        raise FileNotFoundError(f"Startup profile not found for {startup_name}")
            
    # Compile target investors
    if not target_investors:
        logger.info(f"[{startup_name_lower}] No target investors provided. Fetching all members.")
        linkedin_cache_dir = os.path.join(get_env_var("GDRIVE_MOUNT"), "datasets", "sictic_members", "linkedin")
        linkedin_adapter = LinkedInAdapter(cache_dir=linkedin_cache_dir)
        target_investors = linkedin_adapter.get_all_persons()
    
    exclude_investors = exclude_investors or []
    target_investors = [inv for inv in target_investors if inv not in exclude_investors]
    
    logger.info(f"[{startup_name_lower}] Targeting {len(target_investors)} investors.")
    
    # Pre-warm/fetch profiles and appetites
    for inv in target_investors:
        try:
            await investor_appetite(dataset_name="sictic_members", investors=[inv])
        except Exception as e:
            logger.warning(f"[{startup_name_lower}] Failed to refresh/fetch profiles for {inv}: {e}")

    return profile_content, target_investors
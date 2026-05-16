from typing import List, Tuple

from skills.utils.logger import get_logger
from skills.utils.adapters.linkedin import LinkedInAdapter
from skills.utils.slugify import slugify
from skills.utils.storage import get_storage
from skills.investor_appetite.investor_appetite import investor_appetite

logger = get_logger(__name__)


async def fetch_data(startup_name: str, safe_llm_name: str, target_investors: list = None, exclude_investors: list = None) -> Tuple[str, List[str]]:
    storage = get_storage()
    startup_name_lower = startup_name.lower()

    # Fetch startup profile
    raw_startup_filename = f"{startup_name_lower}-profile-{safe_llm_name}"
    insights_dir = f"insights/{startup_name_lower}"
    startup_profile_rel = f"{insights_dir}/{slugify(raw_startup_filename)}.md"
    profile_content = None

    if storage.exists(startup_profile_rel):
        profile_content = storage.read_text(startup_profile_rel)
    elif storage.exists(insights_dir):
        for f in storage.list(insights_dir, suffix=".md"):
            if ("-profile-" in f or "_profile_" in f) and "team_profile" not in f:
                profile_content = storage.read_text(f"{insights_dir}/{f}")
                break

    if not profile_content:
        raise FileNotFoundError(f"Startup profile not found for {startup_name}")

    # Compile target investors
    if not target_investors:
        logger.info(f"[{startup_name_lower}] No target investors provided. Fetching all members.")
        linkedin_cache_dir = str(storage.local_path("datasets/sictic_members/linkedin"))
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

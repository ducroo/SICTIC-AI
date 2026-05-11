import os
import shutil
import asyncio
from pathlib import Path
from typing import List, Union, Optional

from skills.utils.logger import get_logger
from skills.utils.env import get_env_var
from skills.utils.slugify import slugify
from skills.person_profile.person_profile import person_profile
from skills.investor_appetite.investor_appetite import investor_appetite
from skills.utils.adapters.linkedin import LinkedInAdapter

logger = get_logger(__name__)

async def _process_single_member(type_of_profile: str, full_name: str, target_dir: Path) -> Optional[str]:
    try:
        if type_of_profile == "person_profile":
            profile_content = await person_profile(dataset_name="sictic_members", name=full_name)
        elif type_of_profile == "investor_appetite":
            results = await investor_appetite(dataset_name="sictic_members", investors=[full_name])
            profile_content = results.get(full_name)
        else:
            logger.error(f"Unknown type_of_profile: {type_of_profile}")
            return None
            
        if not profile_content:
            logger.warning(f"Got empty profile content for {full_name} ({type_of_profile})")
            return None
            
        target_file = target_dir / f"{slugify(full_name)}.md"
        
        content_is_identical = False
        if target_file.exists():
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                if existing_content == profile_content:
                    content_is_identical = True
            except Exception as e:
                logger.warning(f"Failed to read existing dataset file {target_file}: {e}")
                
        if not content_is_identical:
            try:
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(profile_content)
                logger.info(f"Updated {type_of_profile} dataset for {full_name} at {target_file}")
            except Exception as e:
                logger.error(f"Failed to write dataset file {target_file}: {e}")
        else:
            logger.debug(f"Dataset file for {full_name} is already up to date. Preserving timestamp.")
            
        return profile_content
    except Exception as e:
        logger.error(f"Failed to process {full_name}: {e}")
        return None

async def member_profile(type_of_profile: str, names: Union[str, List[str], None] = None) -> Union[str, dict, None]:
    """
    Fetches the definitive profile for one, many, or all members and ensures it is synced to the datasets directory.
    If names is a string, returns the profile string.
    If names is a list or None, returns a dict mapping names to their profiles.
    """
    gdrive_mount = Path(get_env_var("GDRIVE_MOUNT"))
    
    if type_of_profile not in ["person_profile", "investor_appetite"]:
        logger.error(f"Unknown type_of_profile: {type_of_profile}")
        return None
        
    target_dir = gdrive_mount / "datasets" / type_of_profile
    target_dir.mkdir(parents=True, exist_ok=True)
    
    is_single = isinstance(names, str)
    
    if names is None:
        logger.info(f"No names provided for {type_of_profile}. Fetching all members from LinkedIn cache.")
        linkedin_cache_dir = gdrive_mount / "datasets" / "sictic_members" / "linkedin"
        linkedin_adapter = LinkedInAdapter(cache_dir=str(linkedin_cache_dir))
        names_list = linkedin_adapter.get_all_persons()
    elif is_single:
        names_list = [names]
    else:
        names_list = names
        
    if not names_list:
        logger.warning("No names to process.")
        return None if is_single else {}
        
    logger.info(f"Processing {len(names_list)} members for {type_of_profile}...")
    
    tasks = [_process_single_member(type_of_profile, name, target_dir) for name in names_list]
    results_list = await asyncio.gather(*tasks)
    
    if is_single:
        return results_list[0]
        
    return {name: result for name, result in zip(names_list, results_list)}
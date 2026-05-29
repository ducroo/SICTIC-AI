import asyncio
from typing import List, Optional, Union

from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from skills.person_profile.person_profile import person_profile
from skills.investor_appetite.investor_appetite import investor_appetite
from lib.adapters.linkedin import LinkedInAdapter

logger = get_logger(__name__)


async def _process_single_member(type_of_profile: str, full_name: str, target_dir_rel: str) -> Optional[str]:
    storage = get_storage()
    try:
        if type_of_profile == "person_profile":
            persons = await person_profile(dataset_name="sictic_members", names=full_name)
            profile_content = persons[0].person_profile if persons else None
        elif type_of_profile == "investor_appetite":
            results = await investor_appetite(dataset_name="sictic_members", investors=[full_name])
            profile_content = results.get(full_name)
        else:
            logger.error(f"Unknown type_of_profile: {type_of_profile}")
            return None

        if not profile_content:
            logger.warning(f"Got empty profile content for {full_name} ({type_of_profile})")
            return None

        target_rel = f"{target_dir_rel}/{slugify(full_name)}.md"

        content_is_identical = False
        if storage.exists(target_rel):
            try:
                existing_content = storage.read_text(target_rel)
                if existing_content == profile_content:
                    content_is_identical = True
            except Exception as e:
                logger.warning(f"Failed to read existing dataset file {target_rel}: {e}")

        if not content_is_identical:
            try:
                storage.write_text(target_rel, profile_content)
                logger.info(f"Updated {type_of_profile} dataset for {full_name} at {target_rel}")
            except Exception as e:
                logger.error(f"Failed to write dataset file {target_rel}: {e}")
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
    storage = get_storage()

    if type_of_profile not in ["person_profile", "investor_appetite"]:
        logger.error(f"Unknown type_of_profile: {type_of_profile}")
        return None

    target_dir_rel = f"datasets/{type_of_profile}"
    storage.mkdir(target_dir_rel)

    is_single = isinstance(names, str)

    if names is None:
        logger.info(f"No names provided for {type_of_profile}. Fetching all members from LinkedIn cache.")
        linkedin_adapter = LinkedInAdapter("sictic_members")
        names_list = linkedin_adapter.get_all_persons()
    elif is_single:
        names_list = [names]
    else:
        names_list = names

    if not names_list:
        logger.warning("No names to process.")
        return None if is_single else {}

    logger.info(f"Processing {len(names_list)} members for {type_of_profile}...")

    tasks = [_process_single_member(type_of_profile, name, target_dir_rel) for name in names_list]
    results_list = await asyncio.gather(*tasks)

    if is_single:
        return results_list[0]

    return {name: result for name, result in zip(names_list, results_list)}

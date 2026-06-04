import asyncio
from typing import List, Optional, Union

from lib.dataset_from_insight import dataset_from_insight
from lib.logger import get_logger
from skills.person_profile.person_profile import person_profile
from skills.investor_appetite.investor_appetite import investor_appetite
from lib.adapters.linkedin import LinkedInAdapter

logger = get_logger(__name__)


async def _process_single_member(type_of_profile: str, full_name: str) -> Optional[str]:
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
    if type_of_profile not in ["person_profile", "investor_appetite"]:
        logger.error(f"Unknown type_of_profile: {type_of_profile}")
        return None

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

    tasks = [_process_single_member(type_of_profile, name) for name in names_list]
    results_list = await asyncio.gather(*tasks)

    # Keep the searchable derived dataset in the same canonical shape as all
    # other profile indexing flows: selected insight filenames, model suffixes,
    # and stale-file cleanup are owned by dataset_from_insight().
    await dataset_from_insight(
        insight_name=type_of_profile,
        source_dataset="sictic-members",
    )

    if is_single:
        return results_list[0]

    return {name: result for name, result in zip(names_list, results_list)}

import os
import json
import asyncio
from typing import List
from rapidfuzz import process, fuzz

from lib.model_config import llm_model
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat
from lib.insight_refresh import check_insight_refresh
from lib.adapters.linkedin import LinkedInAdapter
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_filepath import get_insight_filepath
from lib.env import get_env_var
from skills.person_profile.persons_in_dataset import persons_in_dataset
from skills.person_profile.person_dossier import build_person_dossier
from lib.models.person import Person

logger = get_logger(__name__)


def _profile_metadata_header(person: Person) -> str:
    return "\n".join(
        [
            f"Full-name: {person.full_name}",
            f"linkedin-id: {person.linkedin_id}",
            f"Email-addresses: {', '.join(person.email_addresses)}",
            "",
            "",
        ]
    )


def _profile_has_metadata_header(content: str) -> bool:
    lines = [line.strip().lower() for line in content.splitlines()[:3]]
    return lines == ["full-name:", "linkedin-id:", "email-addresses:"] or (
        len(lines) == 3
        and lines[0].startswith("full-name:")
        and lines[1].startswith("linkedin-id:")
        and lines[2].startswith("email-addresses:")
    )


def _ensure_profile_metadata_header(person: Person, content: str) -> str:
    if _profile_has_metadata_header(content):
        return content
    return _profile_metadata_header(person) + content.lstrip()


async def person_profile(
    dataset_name: str,
    names: str | list[str] = None,
    *,
    include_dataset_context: bool = True,
) -> List[Person]:
    """
    Collate a comprehensive profile on a specific person (or list of persons) by searching 
    a given dataset and LinkedIn, returning the full synthesized report.
    If names is None, discovers all persons in the dataset, pre-fetches profiles, and generates all reports.
    Returns a list of fully populated Person objects containing the final Markdown report.
    """
    dataset_slug = slugify(dataset_name)
    
    # 1. Global Discovery
    logger.info(f"[{dataset_slug}] Running global discovery for dataset persons...")
    # discovered_persons is now a List[Person]
    discovered_persons = persons_in_dataset(dataset_slug)
    
    target_persons: List[Person] = []
    
    if not names:
        target_persons = discovered_persons
    else:
        req_names = [names] if isinstance(names, str) else names
        req_persons = [Person(full_name=n) for n in req_names]
        
        for req_p in req_persons:
            best_match = req_p.find_best_match(discovered_persons)
            if best_match:
                logger.info(f"[{dataset_slug}] Matched requested '{req_p.full_name}' to discovered '{best_match.display_name}'.")
                if best_match not in target_persons:
                    target_persons.append(best_match)
            else:
                logger.info(f"[{dataset_slug}] Requested name '{req_p.full_name}' not found natively; adding as sparse person.")
                if req_p not in target_persons:
                    target_persons.append(req_p)
                
    if not target_persons:
        logger.warning(f"[{dataset_slug}] No persons discovered or requested.")
        return []

    # 2. Batch Resolution
    logger.info(f"[{dataset_slug}] Resolving profiles for {len(target_persons)} entities...")
    linkedin_adapter = LinkedInAdapter(dataset_slug)
    all_profiles_raw = await asyncio.to_thread(linkedin_adapter.get_profiles, target_persons)
    
    # De-duplicate the resolved profiles using Person entity resolution
    profiles_to_process: List[Person] = []
    for p in all_profiles_raw:
        best_match = p.find_best_match(profiles_to_process)
        if best_match:
            best_match.merge(p)
            logger.info(f"[{dataset_slug}] Merged resolved profile '{p.display_name}' into existing '{best_match.display_name}'.")
        else:
            profiles_to_process.append(p)

    # 4. Generate profiles concurrently, bounded by the LLM gateway capacity.
    concurrency = int(get_env_var("MAX_CONCURRENT_LLMS"))
    semaphore = asyncio.Semaphore(concurrency)

    async def generate_with_logging(person: Person) -> None:
        try:
            async with semaphore:
                await _generate_single_profile(dataset_slug, person, include_dataset_context=include_dataset_context)
        except Exception as e:
            logger.error(f"[{dataset_slug}] Failed to generate profile for {person.display_name}: {e}")

    await asyncio.gather(*(generate_with_logging(person) for person in profiles_to_process))
            
    return profiles_to_process

async def _generate_single_profile(
    dataset_slug: str,
    person: Person,
    *,
    include_dataset_context: bool = True,
) -> None:
    """
    Worker function to generate a single profile from a fully populated Person Wrapper.
    """
    identifier = person.identifier
    display_name = person.display_name

    # Paths & Refresh Check
    default_llm = llm_model()
    output_file = get_insight_filepath(
        dataset_name=dataset_slug,
        skill_name="person_profile",
        model=default_llm,
        identifier=identifier,
        subdir=True
    )
    needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_slug], output_file)
    if not needs_refresh:
        person.person_profile = _ensure_profile_metadata_header(person, cached_content)
        return

    # Load Configuration
    try:
        conf = config_load()
        query_template = conf['person_profile']['query']
        llm_instructions = conf['person_profile']['llm_instructions']
        try:
            query = query_template.replace("{{name}}", display_name)
        except KeyError:
            query = f"{query_template}\nPerson Name: {display_name}"
    except KeyError as e:
        raise ValueError(f"Missing configuration for person_profile: {e}")

    logger.info(f"[{dataset_slug}] Collating profile for '{display_name}'...")

    # Context Building (Qdrant & Resumes)
    context_parts = []

    if include_dataset_context:
        dossier, mentions = await build_person_dossier(dataset_slug, display_name, query)

        if dossier:
            person.dossier = dossier
            context_parts.append("### DOSSIER DOCUMENTS\n")
            for doc in dossier:
                context_parts.append(doc.to_md())

        if mentions:
            person.mentions = mentions
            context_parts.append("### DOCUMENT MENTIONS\n")
            for m in mentions:
                context_parts.append(m.to_md())

    if person.linkedin_profile:
        linkedin_str = json.dumps(person.linkedin_profile, indent=2)
        context_parts.append("### LINKEDIN PROFILE\n\n" + linkedin_str)

    if not context_parts:
        logger.warning(f"[{dataset_slug}] No documents or LinkedIn profile found for '{display_name}'.")
        profile_output = "No relevant information found."
    else:
        # LLM Generation
        full_context = "\n\n".join(context_parts)
        person_metadata = _profile_metadata_header(person).strip()
        prompt = (
            f"Person metadata:\n{person_metadata}\n\n"
            f"Context from {dataset_slug}:\n{full_context}\n\n"
            f"Query: {query}\n\nInstructions: {llm_instructions}"
        )
        profile_output = await llm_chat(prompt=prompt)
    
    if not profile_output or not profile_output.strip():
        raise ValueError(f"LLM returned empty response for the person profile output of '{display_name}'.")

    profile_output = _ensure_profile_metadata_header(person, profile_output)

    # Save and update object
    storage = get_storage()
    storage.write_text(output_file, profile_output)
    person.person_profile = profile_output
    logger.info(f"[{dataset_slug}] Successfully saved person profile for '{display_name}' to {output_file}")

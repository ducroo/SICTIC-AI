import os
import json

from lib.env import get_env_var
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.person_profile.core.retrieval import get_filtered_chunks
from skills.llm_chat.llm_chat import llm_chat
from lib.insight_refresh import check_insight_refresh
from lib.adapters.linkedin import LinkedInAdapter
from lib.logger import get_logger
from lib.slugify import slugify

logger = get_logger(__name__)

def _get_output_paths(dataset_name: str, name: str) -> tuple[str, str, str, str]:
    """Helper to generate consistent file paths and names. Returns relative storage paths."""
    safe_llm_name = get_env_var("DEFAULT_LLM").split('/')[-1]
    raw_filename_prefix = f"{name}-person-profile"
    output_filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
    output_file = f"insights/{dataset_name}/person_profile/{output_filename}"
    return raw_filename_prefix, safe_llm_name, output_filename, output_file

async def person_profile(dataset_name: str, name: str = None) -> str | dict:
    """
    Collate a comprehensive profile on a specific person by searching a given dataset 
    and LinkedIn, returning the full synthesized report.
    If name is None, iterates over all persons in the dataset and returns a dictionary.
    """
    dataset_name_lower = dataset_name.lower()
    
    if not name:
        logger.info(f"[{dataset_name}] No name provided. Fetching all persons from dataset.")
        linkedin_adapter = LinkedInAdapter(cache_rel=f"datasets/{dataset_name_lower}/linkedin")
        persons_list = linkedin_adapter.get_all_persons()
        
        results = {}
        for p in persons_list:
            try:
                results[p] = await person_profile(dataset_name=dataset_name, name=p)
            except Exception as e:
                logger.error(f"[{dataset_name}] Failed to fetch person profile for {p}: {e}")
                results[p] = f"Error: Could not retrieve person profile. ({e})"
        return results

    raw_filename_prefix, safe_llm_name, output_filename, output_file = _get_output_paths(dataset_name_lower, name)
    
    # 1. Cache Check
    from lib.insight_refresh import check_insight_refresh
    needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_name_lower], output_file, safe_llm_name)
    if not needs_refresh:
        return cached_content

    # 2. Load Configuration
    try:
        conf = config_load()
        query_template = conf['person_profile']['query']
        llm_instructions = conf['person_profile']['llm_instructions']
        try:
            query = query_template.replace("{{name}}", name)
        except KeyError:
            query = f"{query_template}\nPerson Name: {name}"
    except KeyError as e:
        logger.error(f"[{dataset_name}] Missing configuration: {e}")
        raise ValueError(f"Missing configuration for person_profile: {e}")

    logger.info(f"[{dataset_name}] Collating profile for '{name}'...")

    # 3. Retrieve LinkedIn Profile
    linkedin_adapter = LinkedInAdapter(cache_rel=f"datasets/{dataset_name_lower}/linkedin")
    
    import asyncio
    linkedin_profiles = await asyncio.to_thread(linkedin_adapter.get_profiles, [{"name": name}])
    linkedin_profile_data = linkedin_profiles[0] if linkedin_profiles else None
    
    # Determine the unique LinkedIn filename if found
    linkedin_filename = None
    if linkedin_profile_data:
        linkedin_filename = linkedin_adapter.get_filename_for_profile(linkedin_profile_data, fallback_name=name)

    # 4. Retrieve Document Chunks
    filtered_chunks = await get_filtered_chunks(dataset_name_lower, name, query)

    # 5. Deduplicate and Assemble Context
    context_parts = []
    
    if filtered_chunks:
        # Reverse chunks for chronological/relevance ordering based on how retrieval yields them
        filtered_chunks.reverse()
        
        # Filter out chunks that come directly from the LinkedIn file we just pulled
        if linkedin_filename:
            deduped_chunks = [c for c in filtered_chunks if c.document_name != linkedin_filename]
        else:
            deduped_chunks = filtered_chunks
            
        if deduped_chunks:
            chunks_str = "\n\n".join(
                f"[Source: {c.document_name}, Page: {c.page_number}]\n{c.text}"
                for c in deduped_chunks
            )
            context_parts.append("--- DOCUMENT CHUNKS ---\n" + chunks_str)

    if linkedin_profile_data:
        # Format the JSON nicely for the LLM
        linkedin_str = json.dumps(linkedin_profile_data, indent=2)
        context_parts.append("--- LINKEDIN PROFILE ---\n" + linkedin_str)

    if not context_parts:
        logger.warning(f"[{dataset_name}] No documents or LinkedIn profile found for '{name}'.")
        profile_output = "No relevant information found."
    else:
        # 6. LLM Generation
        full_context = "\n\n".join(context_parts)
        prompt = f"Context from {dataset_name_lower}:\n{full_context}\n\nQuery: {query}\n\nInstructions: {llm_instructions}"
        profile_output = await llm_chat(prompt=prompt)
    
    if not profile_output or not profile_output.strip():
        raise ValueError(f"LLM returned empty response for the person profile output of '{name}'.")

    # 7. Save and Return
    get_storage().write_text(output_file, profile_output)
    logger.info(f"[{dataset_name}] Successfully saved person profile for '{name}' to {output_file}")
    return profile_output
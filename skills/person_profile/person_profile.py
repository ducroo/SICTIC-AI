import json
import asyncio
from dataclasses import dataclass
from typing import List

from lib.model_config import llm_model
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.ai_text_generation import generate_markdown
from lib.insights import InsightFile, InsightResult
from lib.people.linkedin import LinkedInResolver
from lib.infrastructure.logging import get_logger
from lib.people.discovery import persons_in_dataset
from lib.people.dossier import build_person_dossier
from lib.people.model import Person
from lib.slugify import slugify
from lib.infrastructure.configuration import get_env_var
from lib.datasets.ingestion import sync_datasets

logger = get_logger(__name__)


@dataclass(slots=True)
class _PersonProfileResult:
    persons: list[Person]
    insights: InsightResult


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

async def _person_profile_result(
    dataset_name: str,
    names: str | list[str] = None,
    *,
    include_dataset_context: bool = True,
) -> _PersonProfileResult:
    """
    Collate a comprehensive profile on a specific person (or list of persons) by searching 
    a given dataset and LinkedIn, returning the full synthesized report.
    If names is None, discovers all persons in the dataset, pre-fetches profiles, and generates all reports.
    Returns populated Person objects and their corresponding insight artifacts.
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
        return _PersonProfileResult(persons=[], insights=[])

    # 2. Batch Resolution
    logger.info(f"[{dataset_slug}] Resolving profiles for {len(target_persons)} entities...")
    linkedin_resolver = LinkedInResolver(dataset_slug)
    all_profiles_raw = await asyncio.to_thread(
        linkedin_resolver.get_profiles,
        target_persons,
    )

    await sync_datasets([dataset_slug], raise_on_error=True)
    
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
    concurrency = int(get_env_var("OLLAMA_NUM_PARALLEL"))
    semaphore = asyncio.Semaphore(concurrency)

    async def generate(person: Person) -> InsightFile:
        async with semaphore:
            return await _generate_single_profile(
                dataset_slug,
                person,
                include_dataset_context=include_dataset_context,
            )

    generated = await asyncio.gather(
        *(generate(person) for person in profiles_to_process),
        return_exceptions=True,
    )
    insights: InsightResult = []
    failures: list[str] = []
    for person, result in zip(profiles_to_process, generated):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            logger.error(
                "[%s] Failed to generate profile for %s",
                dataset_slug,
                person.display_name,
                exc_info=(type(result), result, result.__traceback__),
            )
            failures.append(f"{person.display_name}: {result}")
        else:
            insights.append(result)

    if failures:
        raise RuntimeError(
            f"Failed to generate {len(failures)} person profile(s): "
            + "; ".join(failures)
        )
    return _PersonProfileResult(
        persons=profiles_to_process,
        insights=insights,
    )


async def person_profile(
    dataset_name: str,
    names: str | list[str] = None,
    *,
    include_dataset_context: bool = True,
) -> InsightResult:
    """Generate person profiles and return their managed insight artifacts."""
    result = await _person_profile_result(
        dataset_name,
        names,
        include_dataset_context=include_dataset_context,
    )
    return result.insights


async def person_profile_as_person_objects(
    dataset_name: str,
    names: str | list[str] = None,
    *,
    include_dataset_context: bool = True,
) -> list[Person]:
    """Generate person profiles and return the populated Person objects."""
    result = await _person_profile_result(
        dataset_name,
        names,
        include_dataset_context=include_dataset_context,
    )
    return result.persons

async def _generate_single_profile(
    dataset_slug: str,
    person: Person,
    *,
    include_dataset_context: bool = True,
) -> InsightFile:
    """
    Worker function to generate a single profile from a fully populated Person Wrapper.
    """
    identifier = person.identifier
    display_name = person.display_name

    default_llm = llm_model()

    try:
        conf = load_repository_config("person_profile")
        query_template = conf['query']
        llm_instructions = conf['llm_instructions']
        try:
            query = query_template.replace("{{name}}", display_name)
        except KeyError:
            query = f"{query_template}\nPerson Name: {display_name}"
    except KeyError as e:
        raise ValueError(f"Missing configuration for person_profile: {e}")

    insight = InsightFile(
        dataset=dataset_slug,
        skill="person_profile",
        model=default_llm,
        identifier=identifier,
        subdir=True,
        config_key=query + llm_instructions,
    )
    reusable = insight.find(selection="reusable")
    if reusable:
        person.person_profile_markdown = _ensure_profile_metadata_header(
            person,
            reusable.content(),
        )
        return reusable

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
        profile_output = await generate_markdown(prompt)
    
    profile_output = _ensure_profile_metadata_header(person, profile_output)

    # Save and update object
    insight.save(profile_output)
    person.person_profile_markdown = profile_output
    logger.info(
        f"[{dataset_slug}] Successfully saved person profile for "
        f"'{display_name}' to {insight.path}"
    )
    return insight

"""Resolve the editable roster before individual profiling."""
import asyncio
import re
from lib.insights import InsightFile, InsightResult
from lib.people.discovery import manual_persons_in_dataset, _render_manual_persons_table
from lib.people.model import Person
from lib.people.linkedin import LinkedInResolver, extract_linkedin_id
from lib.datasets.paths import dataset_parsed_path
from lib.storage import get_storage
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.ai_text_generation import Review
from lib.datasets.ingestion import sync_datasets
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from skills.dataset_chat.dataset_chat import dataset_chat_json

logger = get_logger(__name__)

_PROFILE_URL = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[\w%\-]+",
    re.IGNORECASE,
)


def _add_dataset_linkedin_ids(dataset_name: str, persons: list[Person]) -> None:
    """Retain explicit profile URLs, including people absent from name retrieval."""
    storage = get_storage()
    directory = dataset_parsed_path(dataset_name)
    ids = {p.linkedin_id for p in persons if p.linkedin_id}
    filenames = [name for name, _ in storage.list_with_mtime(directory, recursive=True)
                 if name.lower().endswith(".md")]
    for filename in sorted(filenames):
        content = storage.read_text(f"{directory}/{filename}")
        # A named Markdown link explicitly associates an existing name with an ID.
        for label, url in re.findall(r"\[([^\]]+)\]\(([^\s)]+)\)", content):
            if not _PROFILE_URL.fullmatch(url.split("?", 1)[0].rstrip("/")):
                continue
            identifier = extract_linkedin_id(url)
            matches = [p for p in persons if p.full_name and slugify(p.full_name) == slugify(label)]
            if len(matches) == 1 and not matches[0].linkedin_id and identifier not in ids:
                matches[0].linkedin_id = identifier
                ids.add(identifier)
        for match in _PROFILE_URL.finditer(content):
            identifier = extract_linkedin_id(match.group())
            if identifier and identifier not in ids:
                persons.append(Person(linkedin_id=identifier))
                ids.add(identifier)


def _parse_person_names(result: dict) -> list[Person]:
    names = result.get("names")
    if not isinstance(names, list) or not all(
        isinstance(name, str) and name.strip() for name in names
    ):
        raise ValueError("Data-room person discovery requires a list of non-blank names.")
    persons: dict[str, Person] = {}
    for name in names:
        persons.setdefault(slugify(name), Person(full_name=name.strip()))
    return list(persons.values())


def _review_person_names(result: dict | list) -> Review[dict | list]:
    try:
        if not isinstance(result, dict):
            raise ValueError("Data-room person discovery must return an object.")
        _parse_person_names(result)
    except ValueError as error:
        return Review(result, (str(error),))
    return Review(result)


async def persons_in_dataset_as_person_objects(dataset_name: str) -> list[Person]:
    """Use the manual roster first, otherwise discover names from dataset evidence.

    No web search, LinkedIn fetch, or biography generation. Community members
    can be seeded from their existing local LinkedIn cache.
    """
    dataset_slug = slugify(dataset_name)
    manual = manual_persons_in_dataset(dataset_slug)
    if manual is not None:
        return manual
    logger.info("[%s] Discovering people for missing roster", dataset_slug)
    if dataset_slug == "sictic-members":
        persons = await asyncio.to_thread(LinkedInResolver(dataset_slug).get_cached_persons)
    else:
        await sync_datasets([dataset_slug], raise_on_error=True)
        config = load_repository_config("persons_in_dataset", "discovery")
        result = await dataset_chat_json(
            dataset_name=dataset_slug,
            queries=config["queries"],
            prompt=config["instructions"],
            schema=config["response_schema"],
            reviewer=_review_person_names,
            max_chunks=config["max_chunks"],
        )
        # A retrieval failure or no available evidence must not freeze an empty
        # authoritative roster and suppress later discovery.
        if result is not None and not isinstance(result, dict):
            raise ValueError("Person discovery must return an object.")
        persons = _parse_person_names(result) if result is not None else []
        _add_dataset_linkedin_ids(dataset_slug, persons)
    if not persons:
        logger.info("[%s] No people found; leaving roster absent", dataset_slug)
        return []
    # Recheck after asynchronous work in case a deal lead created the roster.
    manual = manual_persons_in_dataset(dataset_slug)
    if manual is not None:
        return manual
    InsightFile(dataset=dataset_slug, skill="persons_in_dataset", model="manual").save(
        _render_manual_persons_table(dataset_name, persons)
    )
    logger.info("[%s] Created editable roster with %d people", dataset_slug, len(persons))
    return persons


async def persons_in_dataset(dataset_name: str) -> InsightResult:
    """Create or reuse the single editable roster and return its artifact."""
    await persons_in_dataset_as_person_objects(dataset_name)
    insight = InsightFile(dataset=slugify(dataset_name), skill="persons_in_dataset", model="manual")
    return [insight] if manual_persons_in_dataset(dataset_name) is not None else []

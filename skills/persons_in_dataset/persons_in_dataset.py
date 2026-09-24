"""Discover startup people and maintain a generated roster with manual precedence."""

import asyncio
from importlib.metadata import PackageNotFoundError, version

from lib.datasets.ingestion import sync_datasets
from lib.datasets.models import Chunk
from lib.datasets.paths import dataset_location
from lib.datasets.search import dataset_search
from lib.datasets.source import iter_parsed_chunks, snapshot_source_files
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.people.linkedin.errors import is_acquisition_unavailable
from lib.infrastructure.logging import get_logger
from lib.infrastructure.web_search import WebSearchAdapter
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.people.discovery import _render_manual_persons_table, manual_persons_in_dataset, read_persons_roster
from lib.people.extraction import PersonExtractor, merge_person, rank_people_by_document_weight
from lib.people.linkedin import LinkedInResolver
from lib.people.linkedin.search import search_people
from lib.people.linkedin.identity import is_linkedin_document
from lib.people.model import Person
from lib.slugify import slugify
from lib.startups.identity import canonical_startup_slug, startup_aliases
from lib.startups.website import website_from_evidence
from lib.storage import get_storage
from skills.persons_in_dataset.reconciliation import reconcile_people
from skills.startup_profile.startup_profile import startup_profile
from skills.startup_website_import.startup_website_import import startup_website_import

logger = get_logger(__name__)


def _roster_insight(dataset: str, config: dict) -> InsightFile:
    location = dataset_location(dataset)
    sources = [(source.filename, source.sha256) for source in snapshot_source_files(get_storage(), location.raw_rel)]
    packages = {}
    for package in ("spacy", config["ner"]["model"]):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return InsightFile(dataset, "persons_in_dataset", llm_model(), config_key=config_cache_key(
        "people-discovery-v2", config, sorted(sources), packages, startup_aliases(),
    ))


def _scan(dataset: str, extractor: PersonExtractor) -> tuple[list[Person], list[Chunk]]:
    chunks = list(iter_parsed_chunks(dataset))
    # LinkedIn JSON is consumed as structured data, never as NER input.
    chunks = [chunk for chunk in chunks if not is_linkedin_document(chunk.document_name)]
    return extractor.extract(chunks), chunks


def _shortlist_ner_people(people: list[Person], limit: int) -> list[Person]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("ner_max_candidates must be a positive integer")
    ranked = rank_people_by_document_weight(people)
    selected = {id(person) for person, _ in ranked[:limit]}
    # Explicit contacts and imported website discoveries are independent inputs.
    result = [person for person in people if id(person) in selected
              or person.linkedin_id or person.email_addresses
              or any(chunk.document_name.startswith("website/") for chunk in person.mentions)]
    logger.info("NER weighted shortlist: %d/%d names selected; %d candidates retained including contacts and website evidence",
                min(limit, len(ranked)), len(ranked), len(result))
    for rank, (person, score) in enumerate(ranked[:limit], 1):
        logger.debug("NER rank %d: %s (document weight %.6f)", rank, person.display_name, score)
    return result


async def _workflow(dataset_name: str) -> tuple[InsightResult, list[Person]]:
    dataset = slugify(dataset_name)
    manual_file = InsightFile(dataset, "persons_in_dataset", "manual")
    if dataset == "sictic-members":
        manual = manual_persons_in_dataset(dataset)
        if manual is not None:
            return [manual_file], manual
        people: list[Person] = []
        for person in await asyncio.to_thread(LinkedInResolver(dataset).get_cached_persons):
            merge_person(people, person)
        if people:
            manual_file.save(_render_manual_persons_table(dataset_name, people))
        return ([manual_file] if people else []), people

    complete = True

    def acquisition_failed(error: InfrastructureError) -> None:
        nonlocal complete
        if not is_acquisition_unavailable(error):
            raise error
        complete = False
        logger.warning("[%s] Discovery incomplete; continuing with available evidence: %s", dataset, error)

    resolver = LinkedInResolver(dataset)
    try:
        await asyncio.to_thread(resolver.resolve_pending_profiles)
    except InfrastructureError as error:
        acquisition_failed(error)
    config = load_repository_config("persons_in_dataset", "discovery")
    insight = _roster_insight(dataset, config)
    reusable = insight.find(selection="reusable")
    if reusable:
        return [reusable], read_persons_roster(reusable)

    await sync_datasets([dataset], raise_on_error=True)
    location = dataset_location(dataset)
    context = ""
    if location.domain == "startups":
        profiles = await startup_profile(dataset)
        context = "\n\n".join(profile.content() for profile in profiles)
    names = [dataset, *(alias for alias in startup_aliases() if canonical_startup_slug(alias) == canonical_startup_slug(dataset))]
    extractor = await asyncio.to_thread(PersonExtractor, **config["ner"])
    people, chunks = await asyncio.to_thread(_scan, dataset, extractor)
    website = website_from_evidence(names, chunks) if location.domain == "startups" else None
    if website:
        try:
            imported = await asyncio.to_thread(
                startup_website_import, dataset, website,
            )
        except InfrastructureError as error:
            if error.provider != "website" or error.kind != InfrastructureErrorKind.SERVICE_UNAVAILABLE:
                raise
            complete = False
            logger.warning("[%s] Website acquisition incomplete; continuing with dataset evidence: %s", dataset, error)
        else:
            if imported.failed_pages:
                complete = False
                logger.warning("[%s] Website acquisition incomplete: %d pages failed; continuing with saved pages", dataset, imported.failed_pages)
            if imported.pages_saved:
                await sync_datasets([dataset], raise_on_error=True)
                people, chunks = await asyncio.to_thread(_scan, dataset, extractor)
    elif not website and location.domain == "startups":
        logger.info("[%s] No unambiguous documented website; skipping website crawl", dataset)
    people = _shortlist_ner_people(people, config["ner_max_candidates"])
    for person in resolver.get_cached_persons():
        merge_person(people, person)
    web_chunks: list[Chunk] = []
    if location.domain == "startups":
        search = WebSearchAdapter()
        company = dataset.replace("-", " ")
        external = await asyncio.to_thread(
            search_people, company, query=config["search"]["linkedin_query"],
            num_results=config["search"]["results_per_query"], search=search,
            on_error=acquisition_failed,
        )
        web_chunks = list({chunk.chunk_id: chunk for person in external for chunk in person.mentions}.values())
        for person in await asyncio.to_thread(extractor.extract, web_chunks):
            merge_person(people, person)
        for person in external:
            merge_person(people, person)
    try:
        await asyncio.to_thread(resolver.get_profiles, people)
    except InfrastructureError as error:
        acquisition_failed(error)
    reconciled: list[Person] = []
    for person in people:
        merge_person(reconciled, person)
    people = reconciled
    team_chunks = await dataset_search(dataset_name=dataset, query=config["queries"],
                                       max_chunks=config["max_chunks"], raise_on_error=True)
    team_chunks = [chunk for chunk in team_chunks if not is_linkedin_document(chunk.document_name)]
    team_chunks = list({chunk.chunk_id: chunk for chunk in [*team_chunks, *web_chunks]}.values())
    if not people and not team_chunks:
        logger.info("[%s] No candidate evidence; leaving roster absent", dataset)
        return [], []
    insight = _roster_insight(dataset, config)
    people = await reconcile_people(people, team_chunks, startup_context=context,
                                    company_names=names, config=config)
    if not people:
        logger.info("[%s] No supported people; leaving existing artifacts unchanged", dataset)
        return [], []
    content = _render_manual_persons_table(dataset_name, people, generated=insight)
    if not complete:
        content = config["incomplete_notice"] + "\n\n" + content
    insight.save(content)
    logger.info("[%s] Saved generated roster with %d people (complete=%s)", dataset, len(people), complete)
    return [insight], people


async def persons_in_dataset_as_person_objects(dataset_name: str) -> list[Person]:
    """Share the canonical roster workflow while retaining in-memory evidence."""
    _, people = await _workflow(dataset_name)
    return people


async def persons_in_dataset(dataset_name: str) -> InsightResult:
    """Return the manual, reusable, or newly generated roster artifacts."""
    insights, _ = await _workflow(dataset_name)
    return insights

"""Bounded evidence preparation and roster synthesis."""

from __future__ import annotations

import json
from copy import deepcopy

from lib.datasets.models import Chunk
from lib.infrastructure.ai_text_generation import generate_json
from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.logging import get_logger
from lib.people.extraction import merge_person
from lib.people.linkedin import condense_profile
from lib.people.model import Person
from lib.people.dossier import is_personal_document, person_in_filename

logger = get_logger(__name__)


def _resolve_existing(person: Person, candidates: list[Person]) -> list[Person]:
    """Screen selected candidates with the shared matching/merge contract."""
    matches = person.find_matches(candidates)
    if not matches and person.linkedin_id:
        without_id = deepcopy(person)
        without_id.linkedin_id = ""
        matches = without_id.find_matches(candidates)
    if not matches:
        logger.info("Discarding unmatched existing person: %s", person.display_name)
        return []
    if len(matches) > 1:
        logger.info("Ambiguous existing person %s: retaining %d candidates separately", person.display_name, len(matches))
        return [deepcopy(candidate) for candidate in matches]
    candidate = matches[0]
    resolved = deepcopy(person)
    # The evidence candidate owns the ID, including when it has no known ID.
    resolved.linkedin_id = candidate.linkedin_id
    resolved.merge(deepcopy(candidate))
    return [resolved]


def _evidence_excerpt(person: Person, chunk: Chunk, limit: int) -> str:
    """Keep a source-linked verbatim window around the identity occurrence."""
    text = chunk.text
    identities = [person.full_name, person.linkedin_id, *person.email_addresses]
    offsets = [text.casefold().find(value.casefold()) for value in identities if value]
    start = max(0, min((offset for offset in offsets if offset >= 0), default=0) - limit // 4)
    excerpt = text[start:start + limit]
    if start:
        excerpt = "…" + excerpt
    if start + limit < len(text):
        excerpt += "…"
    return chunk.model_copy(update={"text": excerpt}).to_md()


def _prepare_prompts(people: list[Person], team_chunks: list[Chunk], *,
                     startup_context: str, company_names: list[str], config: dict) -> list[str]:
    """Size every batch before any generation; never discard candidates to fit."""
    records = []
    omitted = 0
    for person in people:
        evidence = list({chunk.chunk_id: chunk for chunk in person.mentions}.values())
        evidence.sort(key=lambda chunk: (
            person_in_filename(chunk.document_name, person.full_name) if person.full_name else False,
            is_personal_document(chunk.document_name),
            any(name.casefold() in chunk.text.casefold() for name in company_names if name),
        ), reverse=True)
        selected = evidence[:config["evidence_per_person"]]
        omitted += len(evidence) - len(selected)
        record = condense_profile(person, company_names=company_names,
                                  description_chars=config["linkedin_description_chars"])
        record = {key: value for key, value in record.items() if value}
        record["evidence"] = [_evidence_excerpt(person, chunk, config["evidence_excerpt_chars"]) for chunk in selected]
        records.append(json.dumps(record, ensure_ascii=False))
    if omitted:
        logger.info("Selected up to %d passages per candidate; omitted %d additional passages from LLM input",
                    config["evidence_per_person"], omitted)
    prefix = (
        config["instructions"] + "\n\nStartup context:\n" + startup_context
        + "\n\nSupplementary team evidence:\n" + "\n\n".join(chunk.to_md() for chunk in team_chunks)
        + "\n\nCandidate evidence records:\n"
    )
    limit = min(config["max_prompt_chars"], int(get_env_var("OLLAMA_CONTEXT_LENGTH_MAX")) * 2)
    budget = limit - len(prefix)
    if budget <= 0:
        raise ValueError("Startup/team context exceeds the configured person-discovery prompt budget")
    batches: list[list[str]] = [[]]
    used = 0
    for record in records:
        if len(record) + 1 > budget:
            raise ValueError("A candidate exceeds the person-discovery prompt budget; increase the budget or reduce evidence limits")
        if batches[-1] and used + len(record) + 1 > budget:
            batches.append([])
            used = 0
        batches[-1].append(record)
        used += len(record) + 1
    if len(batches) > config["max_reconciliation_calls"]:
        raise ValueError(f"Discovery needs {len(batches)} reconciliation calls; configured maximum is {config['max_reconciliation_calls']}")
    return [prefix + "\n".join(batch) for batch in batches]


async def reconcile_people(people: list[Person], team_chunks: list[Chunk], *,
                           startup_context: str, company_names: list[str], config: dict) -> list[Person]:
    """Reconcile a bounded set of evidence batches using the shared generator."""
    prompts = _prepare_prompts(people, team_chunks, startup_context=startup_context,
                               company_names=company_names, config=config)
    logger.info("Reconciling %d candidates in %d LLM call(s)", len(people), len(prompts))
    accepted: list[Person] = []
    for prompt in prompts:
        result = await generate_json(prompt, config["response_schema"])
        for row in result["existing_persons"]:
            for person in _resolve_existing(Person(**row), people):
                merge_person(accepted, person)
        for row in result["additional_persons"]:
            merge_person(accepted, Person(**row))
    identified = [person for person in accepted if person.identifier]
    if len(identified) != len(accepted):
        logger.info("Discarding %d people without an identity", len(accepted) - len(identified))
    return identified

"""Bounded evidence preparation and roster synthesis."""

from __future__ import annotations

import json
from copy import deepcopy

from litellm import token_counter

from lib.model_config import llm_model
from lib.infrastructure.ai_text_generation.json import schema_prompt_block, json_schema_response_format

from lib.datasets.models import Chunk
from lib.infrastructure.ai_text_generation import generate_json
from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.logging import get_logger
from lib.people.extraction import merge_person, rank_people_by_document_weight
from lib.people.linkedin import condense_profile
from lib.people.model import Person
from lib.people.dossier import is_personal_document, person_in_filename

logger = get_logger(__name__)


def _enrich_person(person: Person, candidates: list[Person]) -> Person:
    """Enrich an LLM-selected identity without restoring discarded candidates."""
    resolved = deepcopy(person)
    matches = person.find_matches(candidates)
    # Exact-ID selection deliberately excludes weaker matches. Still collect
    # compatible ID-less fragments (for example a separately extracted email).
    if person.linkedin_id:
        for candidate in person.find_matches([p for p in candidates if not p.linkedin_id]):
            if candidate not in matches:
                matches.append(candidate)
    ids = {candidate.linkedin_id for candidate in matches if candidate.linkedin_id}
    if not person.linkedin_id and len(ids) > 1:
        logger.info("Conflicting candidate LinkedIn IDs for %s; enriching only from ID-less candidates",
                    person.display_name)
        matches = [candidate for candidate in matches if not candidate.linkedin_id]
    for candidate in matches:
        evidence = deepcopy(candidate)
        # Preserve the LLM's cleaned name over longer NER fragments such as
        # 'Karim Itani Co-Founder'. Person.merge still owns profile-name priority.
        if person.full_name.strip():
            evidence.full_name = ""
        resolved.merge(evidence)
    return resolved


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


def _prepare_prompt(people: list[Person], team_chunks: list[Chunk], *,
                     startup_context: str, company_names: list[str], config: dict) -> tuple[str, list[Person]]:
    """Fill one prompt with all LinkedIn identities, then weighted candidates."""
    ranked = [person for person, _ in rank_people_by_document_weight(people)]
    people = [p for p in ranked if p.linkedin_id] + [p for p in ranked if not p.linkedin_id]
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
    context_limit = int(get_env_var("OLLAMA_CONTEXT_LENGTH_MAX"))
    if context_limit <= 0:
        raise ValueError("OLLAMA_CONTEXT_LENGTH_MAX must be positive")
    # One existing cap; reserve a quarter for output/reasoning and correction overhead.
    input_budget = context_limit * 3 // 4
    model = llm_model()
    schema = config["response_schema"]
    schema_block = schema_prompt_block(schema) + "\n\n"
    format_tokens = token_counter(model=model, text=json.dumps(json_schema_response_format(schema)))

    def count_prompt(prompt: str) -> int:
        return token_counter(model=model, messages=[{"role": "user", "content": schema_block + prompt}]) + format_tokens

    used = count_prompt(prefix)
    if used > input_budget:
        raise ValueError("Startup/team context exceeds the person-discovery token budget; deal-lead review required")
    selected: list[Person] = []
    selected_records: list[str] = []
    for person, record in zip(people, records):
        cost = token_counter(model=model, text=record + "\n")
        if used + cost > input_budget:
            if person.linkedin_id:
                raise ValueError("LinkedIn candidates exceed the person-discovery token budget; deal-lead review required")
            # Keep a prefix of the ranking, never prefer a lower-ranked small record.
            break
        selected.append(person)
        selected_records.append(record)
        used += cost
    prompt = prefix + "\n".join(selected_records)
    # Token boundaries can differ when separately counted records are joined.
    used = count_prompt(prompt)
    while used > input_budget and selected and not selected[-1].linkedin_id:
        selected.pop()
        selected_records.pop()
        prompt = prefix + "\n".join(selected_records)
        used = count_prompt(prompt)
    if used > input_budget:
        raise ValueError("LinkedIn candidates exceed the person-discovery token budget; deal-lead review required")
    logger.info("Single-call roster selection: %d/%d candidates included (%d LinkedIn); %d omitted; estimated input %d/%d tokens (context cap %d)",
                len(selected), len(people), sum(bool(p.linkedin_id) for p in selected),
                len(people) - len(selected), used, input_budget, context_limit)
    return prompt, selected


async def reconcile_people(people: list[Person], team_chunks: list[Chunk], *,
                           startup_context: str, company_names: list[str], config: dict) -> list[Person]:
    """Reconcile one token-bounded prompt using the shared generator."""
    prompt, selected = _prepare_prompt(people, team_chunks, startup_context=startup_context,
                                       company_names=company_names, config=config)
    logger.info("Reconciling %d candidates in one LLM request", len(selected))
    accepted: list[Person] = []
    result = await generate_json(prompt, config["response_schema"])
    for row in [*result["existing_persons"], *result["additional_persons"]]:
        merge_person(accepted, _enrich_person(Person(**row), people))
    identified = [person for person in accepted if person.identifier]
    if len(identified) != len(accepted):
        logger.info("Discarding %d people without an identity", len(accepted) - len(identified))
    return identified

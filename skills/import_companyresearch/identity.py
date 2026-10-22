"""Resolve registry candidates against existing local dossier evidence."""

import json
import re

from lib.datasets.chunking import split_markdown
from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.source import list_source_files, parsed_filepath
from lib.infrastructure.ai_text_generation import generate_json
from lib.infrastructure.ai_text_generation.json import copy_schema
from lib.infrastructure.logging import get_logger
from lib.startups.identity import startup_aliases, canonical_startup_slug

logger = get_logger(__name__)
UID_PATTERN = re.compile(r"\bCHE[\s-]*(\d{3})[.\s]*(\d{3})[.\s]*(\d{3})\b", re.I)


def normalize_uid(value):
    match = UID_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("Expected a Swiss UID such as CHE-123.456.789")
    return "CHE-" + ".".join(match.groups())


async def resolve_uid(startup, company_name, storage, adapter, config):
    location = dataset_location_for_domain(startup, "startups")
    names = [company_name or startup.replace("-", " ")]
    names.extend(alias.replace("-", " ") for alias in startup_aliases()
                 if canonical_startup_slug(alias) == startup)
    passages, uids = [], []
    for filename, mtime in list_source_files(storage, location.raw_rel):
        if filename.startswith("companyresearch-ch/"):
            continue
        raw = f"{location.raw_rel}/{filename}"
        path = raw if filename.lower().endswith((".md", ".txt", ".json")) else parsed_filepath(location.parsed_rel, filename)
        if not storage.exists(path):
            continue
        text = storage.read_text(path)
        for match in UID_PATTERN.finditer(text):
            uid = "CHE-" + ".".join(match.groups())
            uids.append(uid)
            passages.append((3, f"### Source: {filename}\n{text[max(0,match.start()-500):match.end()+500]}"))
        # Explicitly labelled legal names provide lookup terms without another LLM.
        names.extend(re.findall(
            r"(?im)^\s*(?:legal[_ ]name|registered[_ ]name|company[_ ]name|firmenname)\s*[:|]\s*([^\n|]{3,120})", text))
        for chunk in split_markdown(text, filename, mtime):
            lower = chunk.text.casefold()
            priority = 2 if re.search(r"legal|registered|address|company.name|headquarter|firmensitz", lower) else 0
            if any(name.casefold() in lower for name in names):
                priority = max(priority, 1)
            if priority:
                passages.append((priority, chunk.to_md()))
    evidence, remaining = [], config["settings"]["max_identity_characters"]
    for _, text in sorted(passages, key=lambda p: -p[0]):
        if text in evidence:
            continue
        if remaining <= 0:
            logger.info("[%s] Identity evidence reached configured character budget", startup)
            break
        evidence.append(text[:remaining])
        remaining -= len(text)
    if not evidence:
        raise ValueError(f"{startup}: no local identity evidence; supply --uid or add source documents")
    queries = list(dict.fromkeys(uids or names))
    if len(queries) > config["settings"]["max_lookup_queries"]:
        raise ValueError(f"{startup}: too many identity candidates; supply --uid")
    candidates = {}
    for query in queries:
        if 3 <= len(query) <= 120:
            for candidate in await adapter.suggestions(query):
                candidates[candidate["uid"]] = candidate
    if not candidates:
        raise ValueError(f"{startup}: CompanyResearch found no candidate companies")
    schema = copy_schema(config["identity_schema"])
    schema["properties"]["uid"]["enum"] = [*candidates, None]
    result = await generate_json(
        config["identity_instructions"], schema,
        cacheable_prompt_prefix=f"Startup: {startup}\n\nRegistry candidates:\n"
            + json.dumps(list(candidates.values()), ensure_ascii=False)
            + "\n\nDossier evidence:\n" + "\n\n".join(evidence),
    )
    if result["uid"] is None:
        raise ValueError(f"{startup}: unresolved company identity: {result['rationale']}")
    logger.info("[%s] Resolved UID %s: %s", startup, result["uid"], result["rationale"])
    return result["uid"]

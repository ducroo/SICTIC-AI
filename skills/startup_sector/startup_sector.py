"""One independently cached provider classification, defaulting to Dealum."""

from __future__ import annotations

from functools import partial
import json
import re
from typing import Any

from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, find_dataset_location
from lib.datasets.search import dataset_search
from lib.infrastructure.ai_text_generation import generate_json
from lib.infrastructure.ai_text_generation.json import copy_schema, validate_json_schema
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.startups.sources import ensure_startup_dataset
from lib.startups.dealum.importing import APPLICATION_MD, append_txt_to_md_filename
from lib.startups.dealum.manifest import dealum_dataset_rel
from lib.startups.dealum.snapshots import stored_applications
from lib.storage import get_storage
from .taxonomy import provider_record, response_schema, review_classification

logger = get_logger(__name__)
INSUFFICIENT_EVIDENCE = "insufficient evidence"


def _application_proposition(dataset: str, fields: list[str]) -> str:
    """Include explicit business context from the latest local application."""
    location = dataset_location(dataset)
    if location.domain != "startups":
        return ""
    storage = get_storage()
    root = dealum_dataset_rel(dataset)
    if not storage.exists(root):
        return ""
    snapshots = stored_applications(dataset, root)
    folder = f"{root}/{max(snapshots)}" if snapshots else root
    # The importer owns the dated layout and Drive-compatible source filename.
    path = f"{folder}/{append_txt_to_md_filename(APPLICATION_MD)}"
    if not storage.exists(path):
        return ""
    sections = dict(re.findall(
        r"^### ([a-z_]+)\s*\n(.*?)(?=^### |\Z)",
        storage.read_text(path), flags=re.MULTILINE | re.DOTALL,
    ))
    selected = [
        f"### {field}\n\n{sections[field].strip()}"
        for field in fields if sections.get(field, "").strip()
    ]
    if not selected:
        return ""
    source = path.removeprefix(f"{location.raw_rel}/")
    return f"## Application product and customer proposition\n\nSource: {source}\n\n" + "\n\n".join(selected)


def _response_schema(config: dict, provider: str, *, manual: bool = False) -> dict:
    """Stored record for the selected provider only."""
    reference = config["taxonomies"][provider]
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "taxonomy": {"type": "object", "additionalProperties": False,
                "properties": {
                    "provider": {"const": reference["provider"]},
                    "version": {"type": "string"},
                    "status": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["provider", "version", "status", "sources"]},
            "result": response_schema(reference, config["response_schema"]),
            "category_names": {"type": "object"},
            "derived": {"type": "object"},
        },
        "required": (["taxonomy", "result"] if manual
                     else ["taxonomy", "result", "category_names", "derived"]),
    }


def _read_result(insight: InsightFile, config: dict, provider: str) -> dict[str, Any]:
    result = json.loads(insight.content())
    manual = insight.model == "manual"
    if manual and isinstance(result, dict) and "sector" in result and provider == "dealum":
        # Preserve old SICTIC decisions without relabelling them as Dealum.
        result.pop("product_type", None)
        result.pop("product_type_confidence", None)
        schema = copy_schema(config["legacy_response_schema"])
        schema["properties"]["sector"]["enum"] = [*config["sectors"], INSUFFICIENT_EVIDENCE]
        validate_json_schema(result, schema, label=f"Legacy manual classification {insight.path}")
        logger.info("[%s] Retaining legacy manual SICTIC classification; Dealum generation skipped.", insight.dataset)
        return result
    if manual and not insight.subdir and isinstance(result, dict) and "providers" in result:
        # Only the requested provider matters; unrelated manual decisions cannot block it.
        result = result["providers"][provider]
    if manual and isinstance(result, dict):
        result.pop("category_names", None)
        result.pop("derived", None)
    validate_json_schema(result, _response_schema(config, provider, manual=manual),
                         label=f"Startup classification {insight.path}")
    reference = config["taxonomies"][provider]
    review = review_classification(result["result"], reference)
    if review.problems:
        raise ValueError(f"{provider}: {'; '.join(review.problems)}")
    expected = provider_record(result["result"], reference)
    for field in ("category_names", "derived"):
        if manual:
            result[field] = expected[field]
        elif result[field] != expected[field]:
            raise ValueError(f"{provider}: {field} does not match selected taxonomy categories.")
    return result


def _manual_override(insight: InsightFile, provider: str) -> InsightFile | None:
    preferred = insight.find(selection="any")
    if preferred is not None and preferred.model == "manual":
        return preferred
    # Read-only compatibility for the former combined/legacy manual path.
    old = InsightFile(insight.dataset, "startup_sector", insight.model,
                      extension="json").find(selection="any")
    if old is None or old.model != "manual":
        return None
    payload = json.loads(old.content())
    if isinstance(payload, dict):
        if "sector" in payload and provider != "dealum":
            return None
        if isinstance(payload.get("providers"), dict) and provider not in payload["providers"]:
            return None
    return old


async def startup_sector(startup: str, provider: str = "dealum") -> InsightResult:
    """Return one JSON InsightFile for a startup or prepared temporary dataset."""
    config = load_repository_config("startup_sector")
    if provider not in config["taxonomies"]:
        raise ValueError(f"Unknown classification provider {provider!r}; choose from {', '.join(config['taxonomies'])}")
    reference = config["taxonomies"][provider]
    dataset = slugify(startup)
    location = find_dataset_location(dataset)
    if location is None or location.domain == "startups":
        status = await ensure_startup_dataset(startup, sync_after_import=False)
        dataset = status.dataset_slug
        location = dataset_location(dataset)
    if location.domain not in {"startups", "generated"}:
        raise ValueError("startup_sector requires a startup or generated dataset.")

    await sync_datasets([dataset], raise_on_error=True)
    effective_config = {key: config[key] for key in (
        "llm_instructions", "queries", "proposition_fields", "settings", "response_schema",
    )}
    insight = InsightFile(
        dataset=dataset, skill="startup_sector", model=llm_model(), extension="json",
        identifier=provider, subdir=True,
        config_key=config_cache_key(effective_config, reference, load_repository_config("structured_output")),
    )
    if manual := _manual_override(insight, provider):
        _read_result(manual, config, provider)
        return [manual]
    if reusable := insight.find(selection="reusable"):
        _read_result(reusable, config, provider)
        return [reusable]

    proposition = _application_proposition(dataset, config["proposition_fields"])
    # Reserve evidence for every question: a pooled rerank can otherwise let
    # technical detail displace the product and customer propositions.
    queries = config["queries"]
    budget, remainder = divmod(config["settings"]["max_chunks"], len(queries))
    if budget < 1:
        raise ValueError("startup_sector requires an evidence slot for every query.")
    seen_chunk_ids: set[str] = set()
    sections = [proposition] if proposition else []
    for index, query in enumerate(queries):
        chunks = await dataset_search(
            dataset, query, max_chunks=budget + (index < remainder),
            raise_on_error=True,
        )
        passages = []
        for chunk in chunks:
            if chunk.chunk_id not in seen_chunk_ids:
                passages.append(chunk.to_md())
                seen_chunk_ids.add(chunk.chunk_id)
        if not chunks:
            logger.warning("[%s] No evidence retrieved for: %s", dataset, query)
            body = "No source passages retrieved for this question."
        elif not passages:
            body = "Matching source passages are already included above."
        else:
            body = "\n\n---\n\n".join(passages)
        sections.append(f"## Evidence question: {query}\n\n{body}")
    evidence = "\n\n".join(sections)
    prefix = f"Startup dataset: {dataset}\n\nSource evidence:\n{evidence}"
    schema = response_schema(reference, config["response_schema"])
    if proposition or seen_chunk_ids:
        prompt = (f"{config['llm_instructions']}\n\nProvider taxonomy:\n"
                  + json.dumps(reference, ensure_ascii=False))
        classified = await generate_json(
            prompt, schema, partial(review_classification, reference=reference),
            cacheable_prompt_prefix=prefix,
        )
    else:
        logger.warning("[%s] No classification evidence retrieved.", dataset)
        classified = {
            "classifications": {name: {"primary": None, "secondary": []}
                                for name in reference["components"]},
            "confidence": "L",
            "rationale": "No relevant company evidence was retrieved from the dataset.",
            "evidence": [],
        }
        validate_json_schema(classified, schema, label="Empty-retrieval classification")
    result = provider_record(classified, reference)
    logger.info("[%s] Classified with %s (%s).", dataset, provider, reference["status"])

    insight.save(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    logger.info("[%s] Saved startup classifications to %s", dataset, insight.path)
    return [insight]


async def startup_sector_as_dict(startup: str, provider: str = "dealum") -> dict[str, Any]:
    """Read validated data, deriving manual display fields without changing the file."""
    [insight] = await startup_sector(startup, provider=provider)
    return _read_result(insight, load_repository_config("startup_sector"), provider)

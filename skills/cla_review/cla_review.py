"""Lender-side review of one convertible-loan term sheet.

Question 1 of docs/cla-review-design.md (slice 1): identify the term sheet,
extract it with the shared ``captable_build`` CLA checklist, judge it from
the company's angle (``assess_cla``) and from the lender's angle
(``lib.cla_review.assessment``), and render a deterministic report. The
audits against the SECA term sheets, the member's conversion, the existing
loans and the SHA context (slices 2 and 3) are listed in the report as
pending.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from lib.captable.assessment import assess_cla
from lib.captable.cla_extraction import extract_cla
from lib.captable.cla_terms import build_cla_schema
from lib.captable.insights import configured_build_insight, read_build_insight
from lib.captable.render_markdown import _table as markdown_table
from lib.captable.schema import build_artifact_schema
from lib.cla_review.assessment import STATUS_OPEN_QUESTION, assess_lender_angle
from lib.datasets.documents import resolve_document_path
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, dataset_parsed_path
from lib.datasets.source import parsed_filepath
from lib.infrastructure.ai_text_generation import Review
from lib.infrastructure.ai_text_generation.json import validate_json_schema
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.startups.sources import ensure_startup_dataset
from lib.storage import get_storage
from skills.dataset_chat.dataset_chat import dataset_chat_json

logger = get_logger(__name__)

SKILL_NAME = "cla_review"
OUTPUT_SCHEMA_VERSION = 1
RULE_FIELDS = ("value", "unit", "source", "status", "effective_date", "active")
APPROVED_STATUS = "approved"
_IDENTIFICATION_SECTIONS = (
    "document_identification_prompt",
    "document_identification_queries",
    "document_identification_response_schema",
    "document_identification_settings",
    "document_path_resolution",
)
_EXTRACTION_SECTIONS = ("cla_extraction_prompt", "cla_extraction_base_schema", "cla_terms")
PENDING = (
    "Audit against the SECA CLA term sheets (lender-perspective checklists)",
    "My conversion on this cap table (cap, discount, floor over a valuation range)",
    "The existing loans: terms compared, MFN, identical-terms groups, 10/20 non-bank rules before and after N members",
    "The SHA and articles: can the conversion be executed, what accession commits me to",
    "Synthesis of material findings",
)


# --- configuration -------------------------------------------------------------

def load_rules(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the lender-angle rule table; an active rule must be approved."""
    statuses = settings.get("rule_statuses")
    rules = settings.get("rules")
    if not isinstance(statuses, list) or APPROVED_STATUS not in statuses:
        raise ValueError(
            "cla_review.settings.rule_statuses must list the allowed statuses, "
            f"including {APPROVED_STATUS!r}."
        )
    if not isinstance(rules, dict) or not rules:
        raise ValueError("cla_review.settings.rules must be a non-empty object.")
    for name, rule in rules.items():
        if not isinstance(rule, dict):
            raise ValueError(f"cla_review rule {name!r} must be an object.")
        missing = [field for field in RULE_FIELDS if field not in rule]
        if missing:
            raise ValueError(f"cla_review rule {name!r} lacks {missing}.")
        if rule["status"] not in statuses:
            raise ValueError(
                f"cla_review rule {name!r} has unknown status {rule['status']!r}."
            )
        if not isinstance(rule["active"], bool):
            raise ValueError(f"cla_review rule {name!r}: active must be a boolean.")
        if rule["active"] and rule["status"] != APPROVED_STATUS:
            raise ValueError(
                f"cla_review rule {name!r} is active but its status is "
                f"{rule['status']!r}; only {APPROVED_STATUS!r} rules may be active."
            )
    return rules


def active_rules(rules: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The rules a report may judge with; every other rule is an open question at most."""
    return {name: rule for name, rule in rules.items() if rule["active"]}


def load_reference_term_sheets(config: dict[str, Any]) -> dict[str, str]:
    references = config.get("reference_term_sheets")
    if not isinstance(references, dict) or len(references) < 2:
        raise ValueError(
            "cla_review.reference_term_sheets requires the SECA short-form and "
            "long-form term sheets."
        )
    for key, content in references.items():
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"cla_review reference term sheet {key!r} is empty.")
    return references


# --- artifacts -----------------------------------------------------------------

def document_slug(source_path: str) -> str:
    """Artifact identity of a data-room document: its full relative path, slugified."""
    slug = slugify(source_path.removesuffix(".md"))
    if not slug:
        raise ValueError(f"Cannot derive an artifact identity from {source_path!r}.")
    return slug


def _intermediate(dataset: str, identifier: str, config_key: str) -> InsightFile:
    return InsightFile(
        dataset, SKILL_NAME, llm_model(), identifier=identifier, subdir=True,
        extension="json", source_datasets=[dataset], config_key=config_key,
    )


def _manual(insight: InsightFile) -> InsightFile | None:
    preferred = insight.find(selection="any")
    return preferred if preferred is not None and preferred.model == "manual" else None


def _reusable(insight: InsightFile, fresh: bool) -> InsightFile | None:
    return _manual(insight) if fresh else insight.find(selection="reusable")


def _read_json(insight: InsightFile, schema: dict[str, Any], label: str) -> dict[str, Any]:
    data = json.loads(insight.content())
    validate_json_schema(data, schema, label=label)
    return data


def _save_json(insight: InsightFile, data: dict[str, Any], schema: dict[str, Any], label: str) -> InsightFile:
    validate_json_schema(data, schema, label=label)
    insight.save(json.dumps(data, ensure_ascii=False, indent=2))
    return insight


def _extraction_schema() -> dict[str, Any]:
    schema = build_artifact_schema("loan-extraction")
    return {**schema, "$ref": "#/$defs/cla"}


# --- 1. identify ---------------------------------------------------------------

def _review_identification(output: dict | list) -> Review[dict | list]:
    if output["path"] is None:
        return Review(output, (
            "No plausible convertible-loan term sheet could be identified: "
            f"{output['selection_reason']}",
        ))
    return Review(output)


def _classification_context(dataset: str) -> dict[str, Any] | None:
    """Candidates and exclusions from an existing captable_build classification, if any."""
    insight = configured_build_insight(dataset, "classification").find(selection="any")
    if insight is None:
        return None
    documents = read_build_insight(insight)["documents"]
    return {
        "path": insight.path,
        "content": insight.content(),
        "term_sheets": [d["filename"] for d in documents if d["document_class"] == "cla_term_sheet"],
        "executed": [d["filename"] for d in documents if d["document_class"] == "cla_executed"],
    }


def _identification_prompt(instructions: str, classification: dict[str, Any] | None) -> str:
    if classification is None:
        return instructions
    return (
        f"{instructions}\n\n### KNOWN CLASSIFICATION (captable_build, context only)\n\n"
        f"Documents classified as convertible-loan term sheets: {', '.join(classification['term_sheets']) or 'none'}\n"
        f"Documents classified as executed convertible loans (never candidates): {', '.join(classification['executed']) or 'none'}"
    )


def _resolve(dataset: str, proposed_path: str, config: dict[str, Any]) -> tuple[str, float]:
    min_score = float(config["document_path_resolution"]["min_score"])
    if not 0.0 <= min_score <= 100.0:
        raise ValueError("cla_review.document_path_resolution.min_score must be between 0 and 100.")
    source_path, score = resolve_document_path(dataset, proposed_path)
    if score < min_score:
        raise ValueError(
            f"Could not resolve the term sheet path {proposed_path!r} with the required "
            f"score of {min_score:.1f}; best match was {source_path!r} at {score:.1f}."
        )
    if score < 100.0:
        logger.warning("[%s] Resolved term sheet path %r to %r with score %.1f.", dataset, proposed_path, source_path, score)
    return source_path, score


async def _identify(
    dataset: str,
    config: dict[str, Any],
    *,
    document: str | None,
    fresh: bool,
) -> tuple[str, InsightFile]:
    """Return the source path of the term sheet and the identification artifact."""
    schema = config["artifact_schemas"]["identification"]
    classification = _classification_context(dataset)
    identification_config = {name: config[name] for name in _IDENTIFICATION_SECTIONS}
    if document is not None:
        source_path, score = _resolve(dataset, document, config)
        key = config_cache_key(OUTPUT_SCHEMA_VERSION, identification_config, {"selection": "explicit", "document": document})
        insight = _intermediate(dataset, f"{document_slug(source_path)}-identification", key)
        if existing := _reusable(insight, fresh):
            return _read_json(existing, schema, "cla_review identification")["source_path"], existing
        data = {
            "dataset": dataset, "source_path": source_path, "selection": "explicit",
            "document_match": "Explicit",
            "concerns": [] if score >= 100.0 else [f"The supplied path {document!r} was resolved to {source_path!r} (score {score:.1f})."],
            "paths_for_alternative_candidates": [],
            "selection_reason": f"Selected by the caller as {document!r}.",
        }
        return source_path, _save_json(insight, data, schema, "cla_review identification")

    key = config_cache_key(
        OUTPUT_SCHEMA_VERSION, identification_config, {"selection": "automatic"},
        classification["content"] if classification else None,
    )
    insight = _intermediate(dataset, "identification-automatic", key)
    if existing := _reusable(insight, fresh):
        return _read_json(existing, schema, "cla_review identification")["source_path"], existing
    result = await dataset_chat_json(
        dataset_name=dataset,
        queries=config["document_identification_queries"],
        prompt=_identification_prompt(config["document_identification_prompt"], classification),
        schema=config["document_identification_response_schema"],
        reviewer=_review_identification,
        max_chunks=int(config["document_identification_settings"]["max_chunks"]),
    )
    if result is None:
        raise ValueError("No plausible convertible-loan term sheet was found.")
    source_path, score = _resolve(dataset, result["path"], config)
    concerns = list(result["concerns"])
    if score < 100.0:
        concerns.append(f"The selected path {result['path']!r} was resolved to {source_path!r} (score {score:.1f}).")
    data = {
        "dataset": dataset, "source_path": source_path, "selection": "automatic",
        "document_match": result["document_match"], "concerns": concerns,
        "paths_for_alternative_candidates": list(result["paths_for_alternative_candidates"]),
        "selection_reason": result["selection_reason"],
    }
    return source_path, _save_json(insight, data, schema, "cla_review identification")


def _document_text(dataset: str, source_path: str) -> str:
    text = get_storage().read_text(parsed_filepath(dataset_parsed_path(dataset), source_path))
    if not text.strip():
        raise ValueError(f"The parsed text of {source_path!r} is empty.")
    return text


# --- 2. extract, 3. assess -----------------------------------------------------

async def _extract(dataset: str, source_path: str, identification: InsightFile, *, fresh: bool) -> InsightFile:
    captable_config = load_repository_config("captable_build")
    key = config_cache_key(
        OUTPUT_SCHEMA_VERSION, {name: captable_config[name] for name in _EXTRACTION_SECTIONS},
        identification.content(),
    )
    insight = _intermediate(dataset, f"{document_slug(source_path)}-extraction", key)
    schema = _extraction_schema()
    if existing := _reusable(insight, fresh):
        _read_json(existing, schema, "cla_review extraction")
        return existing
    extraction = await extract_cla(dataset, source_path, _document_text(dataset, source_path))
    return _save_json(insight, extraction, schema, "cla_review extraction")


def _assess(dataset: str, source_path: str, extraction: InsightFile, config: dict[str, Any], *, fresh: bool) -> InsightFile:
    settings = config["settings"]
    captable_rules = load_repository_config("captable_build")["assessment_rules"]
    as_of = date.today()
    key = config_cache_key(OUTPUT_SCHEMA_VERSION, settings, captable_rules, extraction.content(), str(as_of))
    insight = _intermediate(dataset, f"{document_slug(source_path)}-assessment", key)
    schema = config["artifact_schemas"]["assessment"]
    if existing := _reusable(insight, fresh):
        _read_json(existing, schema, "cla_review assessment")
        return existing
    terms = _read_json(extraction, _extraction_schema(), "cla_review extraction")
    data = {
        "dataset": dataset, "source_path": source_path, "as_of": str(as_of),
        "company_angle": assess_cla(terms, captable_rules),
        "lender_angle": assess_lender_angle(terms, settings, as_of=as_of),
    }
    return _save_json(insight, data, schema, "cla_review assessment")


# --- 8. report (question 1) ----------------------------------------------------

def _absence(value: Any) -> bool:
    return value is None or value is False or value == "unstated" or value == []


def render_report(
    dataset: str,
    identification: dict[str, Any],
    extraction: dict[str, Any],
    assessment: dict[str, Any],
    *,
    ticket: float | None,
    model: str,
) -> str:
    built = build_cla_schema(load_repository_config("captable_build"))
    terms_rows = []
    for field in built["quoted_fields"]:
        entry = extraction.get(field)
        if not isinstance(entry, dict) or _absence(entry.get("value")):
            continue
        value = entry["value"]
        terms_rows.append((field, ", ".join(value) if isinstance(value, list) else value, entry.get("quote")))
    absent_rows = [(entry["term"], "; ".join(entry["sections_scanned"])) for entry in extraction.get("missing_terms", [])]
    lenders_rows = [(l["name"], l["kind"], l["domicile"], l["principal_amount"]) for l in extraction.get("lenders", [])]
    company_rows = [(f["item"], f["status"], f["severity"], f["detail"]) for f in assessment["company_angle"]]
    lender_rows = [(f["rule"], f["status"], f["severity"], f["rule_status"], f["detail"]) for f in assessment["lender_angle"]]
    judged = sum(1 for f in assessment["lender_angle"] if f["active"])
    open_questions = sum(1 for f in assessment["lender_angle"] if f["status"] == STATUS_OPEN_QUESTION)
    concerns = identification["concerns"] or ["No document-selection concerns were identified."]
    comments = extraction.get("comments")
    parts = [
        f"# CLA term sheet review — {dataset}",
        "",
        f"- **Term sheet:** `{identification['source_path']}`",
        f"- **Selection:** {identification['selection']} (document match {identification['document_match']})",
        f"- **Status of the document:** {extraction.get('status')} — {extraction.get('status_evidence') or 'no status evidence'}",
        f"- **Ticket:** {f'{ticket:,.0f} {extraction.get('principal_currency', {}).get('value') or ''}'.strip() if ticket is not None else 'not supplied (used from slice 2 on)'}",
        f"- **As of:** {assessment['as_of']}",
        f"- **Model:** {model}",
        "",
        "## Document-selection concerns",
        "",
        "\n".join(f"- {concern}" for concern in concerns),
        "",
        "## Lenders named",
        "",
        markdown_table(("Lender", "Kind", "Domicile", "Amount"), lenders_rows) if lenders_rows else "No lender named.",
        "",
        "## Terms with source quotes",
        "",
        markdown_table(("Term", "Value", "Quote"), terms_rows),
        "",
        "## Absent clauses",
        "",
        markdown_table(("Term", "Sections scanned"), absent_rows) if absent_rows else "No absent clause recorded.",
        "",
        "## Company-angle assessment (captable_build rules)",
        "",
        markdown_table(("Item", "Status", "Severity", "Detail"), company_rows),
        "",
        "## Lender-angle assessment",
        "",
        f"{judged} rule(s) approved and judging; {open_questions} open question(s) from rules awaiting approval "
        "(no judgment is issued on an unapproved threshold).",
        "",
        markdown_table(("Rule", "Status", "Severity", "Rule status", "Detail"), lender_rows),
        "",
    ]
    if comments:
        parts += ["## Unusual valuation and conversion provisions (verbatim)", "", comments, ""]
    parts += [
        "## Not yet covered by this report",
        "",
        "\n".join(f"- {item}" for item in PENDING),
        "",
        "---",
        "",
        "This automated review supports, and does not replace, legal review. It is not legal advice.",
        "",
    ]
    return "\n".join(parts)


# --- public API ----------------------------------------------------------------

async def cla_review(
    dataset_name: str,
    *,
    document: str | None = None,
    ticket: float | None = None,
    fresh: bool = False,
) -> list[InsightFile]:
    """Review one CLA term sheet of a startup from the lender's side.

    Returns the Markdown report as the only element; JSON intermediates
    (identification, extraction, assessment) live under ``insights/cla-review/``
    and carry the document identity in their identifier.
    """
    if ticket is not None and ticket <= 0:
        raise ValueError("--ticket must be a positive amount.")
    repository = load_repository_config()
    config = repository[SKILL_NAME]
    load_rules(config["settings"])
    load_reference_term_sheets(config)

    status = await ensure_startup_dataset(dataset_name)
    dataset = status.dataset_slug
    dataset_location(dataset)
    await sync_datasets([dataset], raise_on_error=True)

    source_path, identification = await _identify(dataset, config, document=document, fresh=fresh)
    logger.info("[%s] Reviewing term sheet %s (%s selection)", dataset, source_path, "explicit" if document else "automatic")
    report = InsightFile(
        dataset, SKILL_NAME, llm_model(), identifier=f"{dataset}-{document_slug(source_path)}",
        source_datasets=[dataset],
    )
    if manual := _manual(report):
        logger.info("[%s] Using manual CLA review %s", dataset, manual.path)
        return [manual]

    extraction = await _extract(dataset, source_path, identification, fresh=fresh)
    assessment = _assess(dataset, source_path, extraction, config, fresh=fresh)
    captable_config = load_repository_config("captable_build")
    report.config_key = config_cache_key(
        OUTPUT_SCHEMA_VERSION, config, {name: captable_config[name] for name in _EXTRACTION_SECTIONS},
        captable_config["assessment_rules"], repository["structured_output"], {"ticket": ticket},
        identification.content(), extraction.content(), assessment.content(),
    )
    if not fresh and (existing := report.find(selection="reusable")):
        logger.info("[%s] Using cached CLA review %s", dataset, existing.path)
        return [existing]
    report.save(render_report(
        dataset,
        _read_json(identification, config["artifact_schemas"]["identification"], "cla_review identification"),
        _read_json(extraction, _extraction_schema(), "cla_review extraction"),
        _read_json(assessment, config["artifact_schemas"]["assessment"], "cla_review assessment"),
        ticket=ticket, model=llm_model(),
    ))
    logger.info("[%s] CLA review saved to %s", dataset, report.path)
    return [report]

"""Lender-side review of one convertible-loan term sheet.

Question 1 (slice 1): identify the term sheet, extract it with the shared
``captable_build`` CLA checklist, judge it from the company's angle
(``assess_cla``) and from the lender's angle (``lib.cla_review.assessment``).
Question 2, deterministic part (slice 2): the member's conversion and the
existing loans on the consolidated ``captable_build`` snapshot, read through
``select_consolidated`` and never generated here; an absent or stale
snapshot is insufficient evidence, a malformed one an error. Slice 3 adds
the audits against the selected SECA reference term sheet and against the
company's own SHA, articles and registers (``batch_audit`` with the
lender-perspective checklists in ``config/cla_review/``), and the synthesis
of everything above into material findings.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date
from functools import partial
from typing import Any, NamedTuple

from lib.batch_audit import batch_audit
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import validate_audit_document
from lib.captable.assessment import assess_cla
from lib.captable.cla_extraction import extract_cla
from lib.captable.cla_terms import build_cla_schema
from lib.captable.insights import ConsolidatedUnavailable, build_insight, configured_build_insight, read_build_insight, select_consolidated
from lib.captable.render_markdown import markdown_table
from lib.captable.schema import build_artifact_schema
from lib.cla_review.assessment import STATUS_OPEN_QUESTION, assess_lender_angle
from lib.cla_review.conversion import my_conversion
from lib.cla_review.loans import loan_context
from lib.datasets.documents import resolve_document_path
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, dataset_parsed_path
from lib.datasets.source import parsed_filepath
from lib.infrastructure.ai_text_generation import Review, generate_json, generate_markdown
from lib.infrastructure.ai_text_generation.json import copy_schema, validate_json_schema
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
OUTPUT_SCHEMA_VERSION = 3
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
_RANKING_SECTIONS = ("template_ranking_prompt", "template_ranking_response_schema")
_TERM_SHEET_PLACEHOLDER = "{{term_sheet_under_review}}"


class AuditGroup(NamedTuple):
    """One family of checklists: where they live, which instructions wrap them and what fills the second context block."""
    section: str        # report section key
    folder: str         # config folder holding the checklists
    instructions: str   # config section with the audit instructions
    placeholder: str    # placeholder of the second context block in those instructions
    heading: str        # report heading


AUDIT_GROUPS = (
    AuditGroup("reference", "checklists", "audit_instructions", "{{reference_term_sheet}}",
               "## Audit against the SECA reference term sheet"),
    AuditGroup("executability", "executability_checklists", "executability_instructions", "{{conversion_assumptions}}",
               "## The SHA and articles: can the conversion be executed, what accession commits me to"),
)


class Audit(NamedTuple):
    group: str          # AuditGroup.section
    key: str            # checklist key inside the folder
    insight: InsightFile


class ReviewData(NamedTuple):
    """The validated content of every cla_review intermediate, read once per run."""
    identification: dict[str, Any]
    extraction: dict[str, Any]
    assessment: dict[str, Any]
    conversion: dict[str, Any]
    loans: dict[str, Any]
    reference: dict[str, Any]


_SNAPSHOT_HINT = "run captable_build for this startup, then re-run cla_review"


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


def _placeholders_once(template: str, section: str, placeholders: tuple[str, ...]) -> None:
    for placeholder in placeholders:
        if template.count(placeholder) != 1:
            raise ValueError(f"cla_review.{section} must contain {placeholder} once.")


def validate_audit_config(config: dict[str, Any], captable_config: dict[str, Any]) -> None:
    """Fail before any model call when the audit configuration is incomplete.

    Every checklist folder holds at least one checklist, every instruction file
    carries its two placeholders once, and the settings lists that steer the
    executability audit name real extraction fields and classification classes.
    """
    settings = config["settings"]
    for group in AUDIT_GROUPS:
        checklists = config.get(group.folder)
        if not isinstance(checklists, dict) or not checklists:
            raise ValueError(f"cla_review.{group.folder} must contain at least one checklist.")
        _placeholders_once(config[group.instructions], group.instructions, (_TERM_SHEET_PLACEHOLDER, group.placeholder))
    quoted = set(build_cla_schema(captable_config)["quoted_fields"])
    classes = set(captable_config["classification_response_schema"]["properties"]["documents"]["items"]["properties"]["document_class"]["enum"])
    for name, allowed, what in (("executability_assumption_fields", quoted, "field of config/captable_build/cla_terms.md"),
                                ("constitutional_document_classes", classes, "captable_build document class")):
        values = settings.get(name)
        if not isinstance(values, list) or not values:
            raise ValueError(f"cla_review.settings.{name} must be a non-empty list.")
        unknown = [value for value in values if value not in allowed]
        if unknown:
            raise ValueError(f"cla_review.settings.{name} names no {what}: {unknown}.")


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
    # The slug is readable but lossy (``legal/a-ts.pdf`` and ``legal/a/ts.pdf`` agree);
    # a short digest of the exact path keeps different documents apart.
    return f"{slug}-{hashlib.sha1(source_path.encode('utf-8')).hexdigest()[:6]}"


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
        "documents": documents,
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


def _resolve_explicit(dataset: str, document: str) -> str:
    """The caller names the file; anything short of an exact match is an error, never a substitute."""
    source_path, score = resolve_document_path(dataset, document)
    if score < 100.0:
        raise ValueError(
            f"No document {document!r} in the data room of {dataset!r}; the closest path is {source_path!r} "
            f"(score {score:.1f}). --document names the file exactly."
        )
    return source_path


def _resolve(dataset: str, proposed_path: str, config: dict[str, Any]) -> tuple[str, float]:
    """A model-proposed path, accepted at the configured similarity floor."""
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
        source_path = _resolve_explicit(dataset, document)
        key = config_cache_key(OUTPUT_SCHEMA_VERSION, identification_config, {"selection": "explicit", "source_path": source_path})
        insight = _intermediate(dataset, f"{document_slug(source_path)}-identification", key)
        if existing := _reusable(insight, fresh):
            return _read_json(existing, schema, "cla_review identification")["source_path"], existing
        data = {
            "dataset": dataset, "source_path": source_path, "selection": "explicit",
            "document_match": "Explicit",
            "concerns": [] if document == source_path else [
                f"The supplied name {document!r} names {source_path!r}"
                + ("; a bare basename picks one file when several folders hold that name, so give the full path to be sure."
                   if "/" not in document else ".")
            ],
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

async def _extract(dataset: str, source_path: str, *, fresh: bool) -> InsightFile:
    """Keyed on the document and the extraction configuration only: how the document was selected changes nothing here."""
    captable_config = load_repository_config("captable_build")
    key = config_cache_key(
        OUTPUT_SCHEMA_VERSION, {name: captable_config[name] for name in _EXTRACTION_SECTIONS}, source_path,
    )
    insight = _intermediate(dataset, f"{document_slug(source_path)}-extraction", key)
    schema = _extraction_schema()
    if existing := _reusable(insight, fresh):
        _read_json(existing, schema, "cla_review extraction")
        return existing
    extraction = await extract_cla(dataset, source_path, _document_text(dataset, source_path))
    return _save_json(insight, extraction, schema, "cla_review extraction")


def _assess(
    dataset: str,
    source_path: str,
    extraction: InsightFile,
    terms: dict[str, Any],
    config: dict[str, Any],
    *,
    loans: InsightFile,
    as_of: date,
    fresh: bool,
) -> InsightFile:
    """Both assessments; the lender angle reads the 10/20 counts of question 2, so the loan context is in the key."""
    settings = config["settings"]
    captable_rules = load_repository_config("captable_build")["assessment_rules"]
    key = config_cache_key(OUTPUT_SCHEMA_VERSION, settings, captable_rules, extraction.content(), loans.content(), str(as_of))
    insight = _intermediate(dataset, f"{document_slug(source_path)}-assessment", key)
    schema = config["artifact_schemas"]["assessment"]
    if existing := _reusable(insight, fresh):
        _read_json(existing, schema, "cla_review assessment")
        return existing
    context = _read_json(loans, config["artifact_schemas"]["loan-context"], "cla_review loan-context")["result"]
    data = {
        "dataset": dataset, "source_path": source_path, "as_of": str(as_of),
        "company_angle": assess_cla(terms, captable_rules),
        "lender_angle": assess_lender_angle(
            terms, settings, as_of=as_of,
            non_bank_counts=context["ten_twenty"]["after"] if context is not None else None,
        ),
    }
    return _save_json(insight, data, schema, "cla_review assessment")


# --- 5. and 6. question 2 on the consolidated snapshot -------------------------

def _snapshot(dataset: str) -> tuple[dict[str, Any], InsightFile | None, dict[str, Any] | None]:
    """The consolidated captable_build snapshot as (state, insight, data), never generated here.

    ``absent`` and ``stale`` are insufficient evidence; a malformed snapshot
    (validation error) or any other technical failure propagates.
    """
    if build_insight(dataset, "consolidated").find(selection="any") is None:
        return {"state": "absent", "path": None, "as_of_date": None,
                "detail": f"No consolidated cap-table insight exists for this startup; {_SNAPSHOT_HINT}."}, None, None
    try:
        insight = select_consolidated(dataset)
    except ConsolidatedUnavailable as error:
        return {"state": "stale", "path": None, "as_of_date": None,
                "detail": f"The consolidated cap-table insight is not reusable ({error}); {_SNAPSHOT_HINT}."}, None, None
    data = read_build_insight(insight)
    return {"state": "reusable", "path": insight.path, "as_of_date": data.get("as_of_date"),
            "detail": f"Consolidated snapshot {insight.path} as of {data.get('as_of_date')}."}, insight, data


def _question_2(
    dataset: str,
    source_path: str,
    extraction: InsightFile,
    terms: dict[str, Any],
    config: dict[str, Any],
    *,
    ticket: float | None,
    as_of: date,
    fresh: bool,
) -> tuple[InsightFile, InsightFile]:
    """The conversion and loan-context artifacts; both carry the snapshot state in their key."""
    settings = config["settings"]
    state, snapshot_insight, snapshot = _snapshot(dataset)
    snapshot_key = snapshot_insight.content() if snapshot_insight is not None else state
    artifacts = []
    for stage, compute in (("conversion", my_conversion), ("loan-context", loan_context)):
        key = config_cache_key(OUTPUT_SCHEMA_VERSION, settings, extraction.content(), snapshot_key,
                               {"ticket": ticket}, str(as_of))
        insight = _intermediate(dataset, f"{document_slug(source_path)}-{stage}", key)
        schema = config["artifact_schemas"][stage]
        if existing := _reusable(insight, fresh):
            _read_json(existing, schema, f"cla_review {stage}")
            artifacts.append(existing)
            continue
        data = {
            "dataset": dataset, "source_path": source_path, "as_of": str(as_of), "snapshot": state,
            "result": compute(terms, snapshot, settings, ticket=ticket, as_of=as_of) if snapshot is not None else None,
        }
        artifacts.append(_save_json(insight, data, schema, f"cla_review {stage}"))
    return artifacts[0], artifacts[1]


# --- 4. the SECA reference ------------------------------------------------------

def _form_references(config: dict[str, Any], references: dict[str, str]) -> dict[str, str]:
    """documentation_form values that select a reference without a ranking call."""
    mapping = config["settings"].get("documentation_form_references")
    if not isinstance(mapping, dict):
        raise ValueError("cla_review.settings.documentation_form_references must be an object.")
    selected = {form: key for form, key in mapping.items() if not form.startswith("_")}
    for form, key in selected.items():
        if key not in references:
            raise ValueError(f"cla_review.settings.documentation_form_references maps {form!r} to unknown reference {key!r}.")
    return selected


def _ranking_schema(base_schema: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    schema = copy_schema(base_schema)
    try:
        rankings = schema["properties"]["rankings"]
        rankings["items"]["properties"]["template_key"]["enum"] = keys
    except (KeyError, TypeError) as error:
        raise ValueError("cla_review.template_ranking_response_schema must define properties.rankings.items.properties.template_key.") from error
    rankings["minItems"] = rankings["maxItems"] = len(keys)
    return schema


def _ranking_prompt(text: str, references: dict[str, str], instructions: str) -> str:
    contexts = [f"### TERM SHEET UNDER REVIEW — CONTENT START\n\n{text}\n\n### TERM SHEET UNDER REVIEW — CONTENT END"]
    contexts += [f"### REFERENCE TERM SHEET — CONTENT START\n\nTemplate key: {key}\n\n{reference}\n\n### REFERENCE TERM SHEET — CONTENT END"
                 for key, reference in references.items()]
    return "\n\n".join([instructions, *contexts, "### AUTHORITATIVE RANKING INSTRUCTIONS\n\n" + instructions])


def _review_ranking(output: dict | list, keys: list[str]) -> Review[dict | list]:
    returned = [item["template_key"] for item in output["rankings"]]
    problems = []
    if len(set(returned)) != len(returned):
        problems.append("Reference ranking contains duplicate template keys")
    if set(returned) != set(keys):
        problems.append("Reference ranking must include every configured reference term sheet")
    return Review(output, tuple(problems))


async def _rank_references(text: str, references: dict[str, str], config: dict[str, Any]) -> list[dict[str, str]]:
    keys = sorted(references)
    result = await generate_json(
        _ranking_prompt(text, {key: references[key] for key in keys}, config["template_ranking_prompt"]),
        _ranking_schema(config["template_ranking_response_schema"], keys),
        reviewer=partial(_review_ranking, keys=keys),
    )
    return [dict(item) for item in result["rankings"]]


async def _select_reference(
    dataset: str, source_path: str, extraction: InsightFile, terms: dict[str, Any], config: dict[str, Any], *, fresh: bool,
) -> InsightFile:
    """The SECA reference to audit against: stated by the term sheet, else ranked by the model."""
    references = load_reference_term_sheets(config)
    mapping = _form_references(config, references)
    key = config_cache_key(OUTPUT_SCHEMA_VERSION, {name: config[name] for name in _RANKING_SECTIONS}, mapping, references,
                           extraction.content())
    insight = _intermediate(dataset, f"{document_slug(source_path)}-reference", key)
    schema = config["artifact_schemas"]["reference"]
    if existing := _reusable(insight, fresh):
        _read_json(existing, schema, "cla_review reference")
        return existing
    entry = terms["documentation_form"]
    form = entry["value"] or "unstated"
    data = {"dataset": dataset, "source_path": source_path, "documentation_form": form}
    if form in mapping:
        data.update(selection="stated", reference_key=mapping[form], rankings=[],
                    reason=f"The term sheet names the {form} documentation: {entry['quote'] or 'no quote recorded'}.")
    else:
        rankings = await _rank_references(_document_text(dataset, source_path), references, config)
        data.update(selection="ranked", reference_key=rankings[0]["template_key"], rankings=rankings,
                    reason=f"documentation_form is {form}; ranked by the model: {rankings[0]['rationale_for_rank']}")
    return _save_json(insight, data, schema, "cla_review reference")


# --- 4. and 7. audits ------------------------------------------------------------

def _fill(template: str, section: str, replacements: dict[str, str]) -> str:
    _placeholders_once(template, section, tuple(replacements))
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def _conversion_assumptions(dataset: str, terms: dict[str, Any], settings: dict[str, Any]) -> str:
    """What the term sheet relies on for its conversion, as extracted, plus the constitutional documents known to captable_build.

    The field and class lists come from ``settings.json`` and were validated
    against the extraction checklist and the classification schema at start.
    """
    lines = ["Extracted from the term sheet (value; quote):", ""]
    for field in settings["executability_assumption_fields"]:
        entry = terms[field]
        value = entry["value"]
        rendered = "not stated" if _absence(value) else (", ".join(value) if isinstance(value, list) else str(value))
        lines.append(f"- {field}: {rendered}; {entry['quote'] or 'no quote'}")
    classification = _classification_context(dataset)
    lines += ["", "Constitutional documents identified by captable_build (search these first):", ""]
    if classification is None:
        lines.append("- none: no captable_build classification exists for this startup; rely on retrieval.")
    else:
        wanted = set(settings["constitutional_document_classes"])
        found = [f"- {d['filename']} ({d['document_class']})" for d in classification["documents"] if d["document_class"] in wanted]
        lines += found or [f"- none classified as any of: {', '.join(settings['constitutional_document_classes'])}."]
    return "\n".join(lines)


async def _run_audits(
    dataset: str, source_path: str, terms: dict[str, Any], reference_key: str, config: dict[str, Any],
) -> list[Audit]:
    """Every configured checklist, audited against the selected reference or the company's own documents.

    ``batch_audit`` owns the audit artifacts and their reuse; the document
    identity enters the identifier through ``skill_name``. The audits come
    back in a stable order and each one is complete.
    """
    references = load_reference_term_sheets(config)
    term_sheet_context = f"Originating path: {source_path}\n\n{_document_text(dataset, source_path)}"
    second_context = {
        "{{reference_term_sheet}}": f"Reference key: {reference_key}\n\n{references[reference_key]}",
        "{{conversion_assumptions}}": _conversion_assumptions(dataset, terms, config["settings"]),
    }
    jobs: list[tuple[str, str, Any]] = []
    for group in AUDIT_GROUPS:
        instructions = _fill(config[group.instructions], group.instructions,
                             {_TERM_SHEET_PLACEHOLDER: term_sheet_context, group.placeholder: second_context[group.placeholder]})
        for key in sorted(config[group.folder]):
            jobs.append((group.section, key, batch_audit(
                dataset_name=dataset, checklist_markdown=config[group.folder][key],
                skill_name=f"{SKILL_NAME}-{document_slug(source_path)}",
                llm_instructions=instructions, response_schema=config["audit_response_schema"],
            )))
    results = await asyncio.gather(*(job[2] for job in jobs))
    audits = []
    for (group_section, key, _), insight in zip(jobs, results):
        validate_audit_document(json.loads(insight.content()), require_complete=True)
        audits.append(Audit(group_section, key, insight))
    return audits


# --- 8. synthesis -----------------------------------------------------------------

def _synthesis_prompt(dataset: str, config: dict[str, Any], audits: list[Audit], review: ReviewData) -> str:
    blocks = []
    for audit in audits:
        label = "AUDIT AGAINST THE SECA REFERENCE" if audit.group == "reference" else "EXECUTABILITY AUDIT"
        blocks.append(f"### {label}: {audit.key}\n\n{audit.insight.content()}")
    blocks.append("### ASSESSMENTS (company angle, lender angle)\n\n" + json.dumps(review.assessment, ensure_ascii=False, indent=2))
    blocks.append("### QUESTION 2 (conversion, existing loans)\n\n"
                  + json.dumps({"conversion": review.conversion, "loans": review.loans}, ensure_ascii=False, indent=2))
    instructions = config["summary_instructions"].replace("{{startup}}", dataset)
    return ("### COMBINED REVIEW MATERIAL — CONTENT START\n\n" + "\n\n".join(blocks)
            + "\n\n### COMBINED REVIEW MATERIAL — CONTENT END\n\n### AUTHORITATIVE SUMMARY INSTRUCTIONS\n\n" + instructions)


# --- 8. report -------------------------------------------------------------------

def _absence(value: Any) -> bool:
    return value is None or value is False or value == "unstated" or value == []


def _money(value: Any) -> str:
    return f"{value:,.0f}" if isinstance(value, (int, float)) else "—"


def _plain(value: Any) -> Any:
    """Table-friendly rendering of a resolved input: no JSON quotes in Markdown cells."""
    if isinstance(value, dict):
        return "; ".join(f"{key} {_plain(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(str(_plain(item)) for item in value)
    if value is None:
        return "none"
    if isinstance(value, float) and value.is_integer():
        return _money(value)
    return value


def _render_question_2(conversion: dict[str, Any], loans: dict[str, Any]) -> list[str]:
    state = conversion["snapshot"]
    parts = ["## Question 2 — the terms in this company", ""]
    if state["state"] != "reusable":
        parts += [f"**Insufficient evidence ({state['state']} cap-table snapshot).** {state['detail']}", ""]
        return parts
    result, context = conversion["result"], loans["result"]
    parts += [f"Cap-table snapshot: `{state['path']}` as of {state['as_of_date']}.", "",
              "### Inputs, resolved before any number", "",
              markdown_table(("Input", "Value", "Source", "Note"), [
                  (name, _plain(item["value"]), item["source"], item["note"]) for name, item in result["inputs"].items()]), ""]
    if result["assumptions"]:
        parts += ["Assumptions applied:", "", "\n".join(f"- {text}" for text in result["assumptions"]), ""]
    if result["omitted"]:
        parts += ["Calculations omitted:", "", "\n".join(f"- {item['calculation']}: {item['reason']}" for item in result["omitted"]), ""]
    parts += ["### My conversion", ""]
    if result["crossover_valuation"] is not None:
        parts += [f"Cap and discount cross at a pre-money valuation of {_money(result['crossover_valuation'])}: "
                  "below it the discount sets my price, above it the cap.", ""]
    if result["balances"]:
        parts += ["Balance of my ticket, principal plus accrued interest: "
                  + "; ".join(f"{label}: {_money(value)}" for label, value in result["balances"].items()), ""]
    if result["scenarios"]:
        parts += [markdown_table(
            ("Conversion date", "Pre-money", "Round price", "My price", "Binding", "My shares", "My %", "Other new lenders %", "Existing loans %", "New investor %"),
            [(r["conversion_date"], _money(r["pre_money"]), r["round_price"], r["my_price"], r["binding_term"], _money(r["my_shares"]),
              f"{r['my_ownership_pct']:.2f}", f"{r['other_new_lenders_ownership_pct']:.2f}", f"{r['existing_loans_ownership_pct']:.2f}",
              f"{r['new_investor_ownership_pct']:.2f}") for r in result["scenarios"]]), ""]
        warnings = sorted({w for r in result["scenarios"] for w in r["warnings"]})
        if warnings:
            parts += ["Warnings:", "", "\n".join(f"- {w}" for w in warnings), ""]
    if result["stamp_duty"]:
        duty = result["stamp_duty"]
        parts += [f"Stamp duty on the round: {_money(duty['duty'])} CHF on a contribution of {_money(duty['round_contribution'])} "
                  f"(paid in before: {_money(duty['cumulative_paid_in_before'])}). {duty['note']}.", ""]
    parts += ["### The existing loans", "",
              markdown_table(("Document", "Role", "Lenders", "Principal", "Currency", "Cap", "Discount %", "Floor", "Denominator", "Maturity", "Interest", "Subordinated", "MFN", "Pro-rata"),
                             [(row["document"], row["role"], ", ".join(n for n in row["lenders"] if n), _money(row["principal_total"]), row["principal_currency"],
                               _money(row["valuation_cap"]), row["discount_pct"], _money(row["valuation_floor"]), row["denominator_basis"], row["maturity_date"],
                               f"{row['interest_mode']} {row['interest_rate_pct'] if row['interest_rate_pct'] is not None else ''}".strip(),
                               row["subordinated"], row["mfn_clause"], row["pro_rata_rights"]) for row in context["comparison"]]), "",
              "Most-favoured-nation reading:", "", "\n".join(f"- {text}" for text in context["mfn"]["readings"]), "",
              ("The term sheet joins the identical-terms group of " + ", ".join(context["identical_terms"]["documents"]))
              if context["identical_terms"]["joins_existing_group"] else "The term sheet forms a new identical-terms group.", "",
              "### 10/20 non-bank rules", "",
              markdown_table(("", "Lenders on identical terms (max group)", "10 rule", "All lenders", "20 rule"), [
                  ("Today", context["ten_twenty"]["before"]["max_lenders_on_identical_terms"], context["ten_twenty"]["before"]["ten_rule"],
                   context["ten_twenty"]["before"]["total_lenders_all_terms"], context["ten_twenty"]["before"]["twenty_rule"]),
                  (f"After {context['ten_twenty']['member_count_n']} members join on these terms",
                   context["ten_twenty"]["after"]["max_lenders_on_identical_terms"], context["ten_twenty"]["after"]["ten_rule"],
                   context["ten_twenty"]["after"]["total_lenders_all_terms"], context["ten_twenty"]["after"]["twenty_rule"])]), "",
              context["ten_twenty"]["note"], ""]
    caveats = context["ten_twenty"]["after"]["caveats"]
    if caveats:
        parts += ["\n".join(f"- {c}" for c in caveats), ""]
    parts += ["### Maturities", "",
              markdown_table(("Document", "Role", "Maturity"), [(m["document"], m["role"], m["maturity_date"]) for m in context["maturities"]]), ""]
    return parts


def _render_audits(audits: list[Audit]) -> list[str]:
    parts: list[str] = []
    for group in AUDIT_GROUPS:
        parts += [group.heading, ""]
        for audit in audits:
            if audit.group != group.section:
                continue
            title = json.loads(audit.insight.content())["checklist_title"]
            parts += [f"### {title}", "", f"Checklist `{audit.key}`, audit `{audit.insight.path}`.", "",
                      json_to_markdown_table(audit.insight), ""]
    return parts


def _render_header(dataset: str, review: ReviewData, *, ticket: float | None, model: str) -> list[str]:
    identification, extraction, reference = review.identification, review.extraction, review.reference
    currency = extraction["principal_currency"]["value"] or ""
    ticket_line = (f"{ticket:,.0f} {currency}".strip() if ticket is not None
                   else "not supplied; question 2 derives one as a labelled assumption")
    concerns = identification["concerns"] or ["No document-selection concerns were identified."]
    return [
        f"# CLA term sheet review — {dataset}",
        "",
        f"- **Term sheet:** `{identification['source_path']}`",
        f"- **Selection:** {identification['selection']} (document match {identification['document_match']})",
        f"- **Status of the document:** {extraction['status']} — {extraction['status_evidence'] or 'no status evidence'}",
        f"- **Ticket:** {ticket_line}",
        f"- **As of:** {review.assessment['as_of']}",
        f"- **Reference term sheet:** `{reference['reference_key']}` ({reference['selection']}: {reference['reason']})",
        f"- **Model:** {model}",
        "",
        "## Document-selection concerns",
        "",
        "\n".join(f"- {concern}" for concern in concerns),
        "",
    ]


def _render_question_1(extraction: dict[str, Any], assessment: dict[str, Any]) -> list[str]:
    built = build_cla_schema(load_repository_config("captable_build"))
    terms_rows = []
    for field in built["quoted_fields"]:
        entry = extraction[field]
        if _absence(entry["value"]):
            continue
        value = entry["value"]
        terms_rows.append((field, ", ".join(value) if isinstance(value, list) else value, entry["quote"]))
    absent_rows = [(entry["term"], "; ".join(entry["sections_scanned"])) for entry in extraction["missing_terms"]]
    lenders_rows = [(l["name"], l["kind"], l["domicile"], l["principal_amount"]) for l in extraction["lenders"]]
    company_rows = [(f["item"], f["status"], f["severity"], f["detail"]) for f in assessment["company_angle"]]
    lender_rows = [(f["rule"], f["status"], f["severity"], f["rule_status"], f["detail"]) for f in assessment["lender_angle"]]
    judged = sum(1 for f in assessment["lender_angle"] if f["active"])
    open_questions = sum(1 for f in assessment["lender_angle"] if f["status"] == STATUS_OPEN_QUESTION)
    parts = [
        "## Question 1 — the terms themselves",
        "",
        "### Lenders named",
        "",
        markdown_table(("Lender", "Kind", "Domicile", "Amount"), lenders_rows),  # the schema requires at least one lender
        "",
        "### Terms with source quotes",
        "",
        markdown_table(("Term", "Value", "Quote"), terms_rows),
        "",
        "### Absent clauses",
        "",
        markdown_table(("Term", "Sections scanned"), absent_rows) if absent_rows else "No absent clause recorded.",
        "",
        "### Company-angle assessment (captable_build rules)",
        "",
        markdown_table(("Item", "Status", "Severity", "Detail"), company_rows),
        "",
        "### Lender-angle assessment",
        "",
        f"{judged} rule(s) approved and judging; {open_questions} open question(s) from rules awaiting approval "
        "(no judgment is issued on an unapproved threshold).",
        "",
        markdown_table(("Rule", "Status", "Severity", "Rule status", "Detail"), lender_rows),
        "",
    ]
    if extraction["comments"]:
        parts += ["### Unusual valuation and conversion provisions (verbatim)", "", extraction["comments"], ""]
    return parts


def render_report(
    dataset: str,
    review: ReviewData,
    audits: list[Audit],
    synthesis: str,
    *,
    ticket: float | None,
    model: str,
) -> str:
    parts = _render_header(dataset, review, ticket=ticket, model=model)
    parts += _render_question_1(review.extraction, review.assessment)
    parts += _render_question_2(review.conversion, review.loans)
    parts += _render_audits(audits)
    parts += [
        "## Synthesis of material findings",
        "",
        synthesis.strip(),
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

    Returns the Markdown report as the only element. JSON intermediates
    (identification, extraction, assessment, conversion, loan-context,
    reference) live under ``insights/cla-review/``; the audits live under
    ``insights/batch-audit/`` because ``batch_audit`` owns them. Every
    intermediate carries the document identity in its identifier.
    ``fresh`` regenerates the cla_review intermediates and the report; the
    audits are reused by ``batch_audit`` on their own configuration key.
    """
    if ticket is not None and ticket <= 0:
        raise ValueError("--ticket must be a positive amount.")
    repository = load_repository_config()
    config = repository[SKILL_NAME]
    captable_config = repository["captable_build"]
    load_rules(config["settings"])
    load_reference_term_sheets(config)
    validate_audit_config(config, captable_config)

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

    as_of = date.today()
    extraction = await _extract(dataset, source_path, fresh=fresh)
    terms = _read_json(extraction, _extraction_schema(), "cla_review extraction")
    conversion, loans = _question_2(dataset, source_path, extraction, terms, config, ticket=ticket, as_of=as_of, fresh=fresh)
    assessment = _assess(dataset, source_path, extraction, terms, config, loans=loans, as_of=as_of, fresh=fresh)
    reference = await _select_reference(dataset, source_path, extraction, terms, config, fresh=fresh)
    schemas = config["artifact_schemas"]
    review = ReviewData(
        identification=_read_json(identification, schemas["identification"], "cla_review identification"),
        extraction=terms,
        assessment=_read_json(assessment, schemas["assessment"], "cla_review assessment"),
        conversion=_read_json(conversion, schemas["conversion"], "cla_review conversion"),
        loans=_read_json(loans, schemas["loan-context"], "cla_review loan-context"),
        reference=_read_json(reference, schemas["reference"], "cla_review reference"),
    )
    audits = await _run_audits(dataset, source_path, terms, review.reference["reference_key"], config)
    report.config_key = config_cache_key(
        OUTPUT_SCHEMA_VERSION, config, {name: captable_config[name] for name in _EXTRACTION_SECTIONS},
        captable_config["assessment_rules"], repository["structured_output"], {"ticket": ticket},
        identification.content(), extraction.content(), assessment.content(), conversion.content(), loans.content(),
        reference.content(), *(audit.insight.content() for audit in audits),
    )
    if not fresh and (existing := report.find(selection="reusable")):
        logger.info("[%s] Using cached CLA review %s", dataset, existing.path)
        return [existing]
    synthesis = await generate_markdown(_synthesis_prompt(dataset, config, audits, review))
    report.save(render_report(dataset, review, audits, synthesis, ticket=ticket, model=llm_model()))
    logger.info("[%s] CLA review saved to %s", dataset, report.path)
    return [report]

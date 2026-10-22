"""Assess applicants against shared job criteria using canonical person evidence."""

import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

from lib.batch_audit import batch_audit
from lib.batch_audit.checklist import ChecklistCheck, parse_checklist
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import validate_audit_document
from lib.insights import InsightFile, InsightResult
from lib.infrastructure.ai_text_generation import Review, generate_json, generate_markdown
from lib.infrastructure.ai_text_generation.json import copy_schema
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.model_config import llm_model
from lib.people.dossier import build_person_dossier
from lib.people.model import Person
from lib.slugify import slugify
from skills.person_profile.person_profile import person_profile_as_person_objects
from skills.persons_in_dataset.persons_in_dataset import persons_in_dataset

logger = get_logger(__name__)


def _checklist(criteria: str, identifier: str) -> str:
    return f"# {identifier}\n\n{criteria.strip()}\n"


def _review_criteria(output: str) -> Review[str]:
    try:
        parse_checklist(_checklist(output, "applicant"))
    except ValueError as error:
        return Review(output, (str(error),))
    return Review(output)


async def _job_criteria(dataset: str, supplied: str | None, config: dict) -> InsightFile:
    insight = InsightFile(
        dataset, "job_criteria", llm_model(),
        config_key=config_cache_key(config["criteria_instructions"], supplied),
    )
    # With no new source material, existing criteria are an intentional input.
    selected = insight.find(selection="reusable" if supplied is not None else "any")
    if selected:
        return selected
    if supplied is None or not supplied.strip():
        raise ValueError("Supply criteria/a job advert or create a job-criteria insight.")
    result = await generate_markdown(
        config["criteria_instructions"] + "\n\nJob material:\n" + supplied,
        reviewer=_review_criteria,
    )
    insight.save(result)
    return insight


async def _evidence(dataset: str, person: Person, config: dict) -> str:
    # Always gather both kinds of evidence, whether the profile was reused or new.
    gathered_dossier, gathered_mentions = await build_person_dossier(
        dataset, person.display_name,
        config["dossier_query"].replace("{{name}}", person.display_name),
        person=person,
    )
    dossier = list({c.chunk_id: c for c in [*person.dossier, *gathered_dossier]}.values())
    mentions = list({c.chunk_id: c for c in [*person.mentions, *gathered_mentions]}.values())
    dossier_documents = {chunk.document_name for chunk in dossier}
    mentions = [chunk for chunk in mentions if chunk.document_name not in dossier_documents]
    parts = [f"Applicant: {person.display_name}\nIdentifier: {person.identifier}"]
    parts.extend(chunk.to_md() for chunk in dossier)
    if mentions:
        parts.append("Applicant document passages:\n" + "\n\n".join(
            chunk.to_md() for chunk in mentions
        ))
    if person.linkedin_profile:
        parts.append("LinkedIn profile:\n" + json.dumps(person.linkedin_profile, ensure_ascii=False))
    if person.person_profile_markdown:
        parts.append("Generated person profile:\n" + person.person_profile_markdown)
    return "\n\n".join(parts)


def _cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def _overview_schema(identifiers: list[str], template: dict) -> dict:
    schema = copy_schema(template)
    rationale_schema = schema["additionalProperties"]
    schema["properties"] = {
        identifier: copy_schema(rationale_schema) for identifier in identifiers
    }
    schema["required"] = identifiers
    schema["additionalProperties"] = False
    return schema


def _review_ranks(output: dict) -> Review[dict]:
    ranks = sorted(item["rank"] for item in output.values())
    if ranks != list(range(1, len(output) + 1)):
        return Review(output, ("Assign each rank from 1 to the candidate count exactly once.",))
    return Review(output)


def _person_context(person: Person) -> dict:
    context = asdict(person)
    context["dossier"] = [chunk.to_md() for chunk in person.dossier]
    context["mentions"] = [chunk.to_md() for chunk in person.mentions]
    return context


@dataclass
class ApplicantAssessment:
    person: Person
    rows: list[dict]
    audit: InsightFile
    report: InsightFile


async def _assess_person(
    dataset: str, person: Person, criteria_text: str,
    checks: list[ChecklistCheck], config: dict,
) -> ApplicantAssessment:
    evidence = await _evidence(dataset, person, config)
    audit = await batch_audit(
        dataset, _checklist(criteria_text, person.identifier),
        skill_name="recruiting",
        response_schema=config["audit_response_schema"],
        llm_instructions=config["audit_instructions"],
        evidence=evidence, retrieve=False,
    )
    data = json.loads(audit.content())
    validate_audit_document(data, require_complete=True)
    rows = [check for chapter in data["chapters"] for check in chapter["checks"]]
    if [row["check"] for row in rows] != [check.name for check in checks]:
        raise ValueError("Audit criteria do not match the requested checklist.")
    report = InsightFile(
        dataset, "recruiting", llm_model(), identifier=person.identifier,
        subdir=True, config_key=config_cache_key(audit.content(), config),
    )
    selected = report.find(selection="reusable")
    if selected:
        report = selected
    else:
        report.save(
            f"# Recruiting assessment: {person.display_name}\n\n"
            + json_to_markdown_table(audit)
        )
    logger.info("[%s] Assessed applicant %s", dataset, person.display_name)
    return ApplicantAssessment(person, rows, audit, report)


async def _build_overview(
    dataset: str, criteria_text: str, checks: list[ChecklistCheck],
    assessed: list[ApplicantAssessment], config: dict,
) -> InsightFile:
    payload = [
        {"identifier": item.person.identifier, "name": item.person.display_name,
         "person": _person_context(item.person),
         "assessments": item.rows, "report": item.report.content()}
        for item in assessed
    ]
    overview = InsightFile(
        dataset, "recruiting", llm_model(),
        config_key=config_cache_key(config, criteria_text, payload),
    )
    if selected := overview.find(selection="reusable"):
        return selected
    # Keep freshness dependencies unchanged; omit duplicate generated prose only
    # from the model input. Manual reports remain explicit synthesis evidence.
    synthesis_payload = [
        {key: value for key, value in record.items()
         if key != "report" or item.report.model == "manual"}
        for record, item in zip(payload, assessed)
    ]
    rankings = await generate_json(
        config["overview_instructions"] + "\n\nCriteria:\n" + criteria_text
        + "\n\nAssessments:\n"
        + json.dumps(synthesis_payload, ensure_ascii=False),
        schema=_overview_schema(
            [item.person.identifier for item in assessed], config["overview_response_schema"],
        ),
        reviewer=_review_ranks,
    )
    score_schema = config["audit_response_schema"]["properties"]["score"]
    headers = ["Rank", "Full name", *(check.name for check in checks), "Rationale"]
    lines = [
        f"# Recruiting: {dataset}\n",
        f"Scores: {score_schema['minimum']}–{score_schema['maximum']}; "
        + score_schema["description"] + "\n\n"
        "Scores come from structured audits; see linked reports for any manual corrections.\n",
        "| " + " | ".join(_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for item in sorted(assessed, key=lambda item: rankings[item.person.identifier]["rank"]):
        person, rows, report = item.person, item.rows, item.report
        # Both artifacts are managed by InsightFile; only the display link is relative.
        relative = PurePosixPath(report.path).relative_to(PurePosixPath(overview.path).parent)
        name = person.display_name.replace("[", r"\[").replace("]", r"\]")
        scores = [
            row["result"]["score"] if row["result"]["score"] is not None else "?"
            for row in rows
        ]
        ranking = rankings[person.identifier]
        cells = [ranking["rank"], f"[{name}]({quote(str(relative))})",
                 *scores, ranking["rationale"]]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    overview.save("\n".join(lines) + "\n")
    return overview


async def recruiting(dataset_name: str, criteria: str | None = None) -> InsightResult:
    """Return criteria, individual assessments and overview; never send outreach."""
    dataset = slugify(dataset_name)
    config = load_repository_config("recruiting")
    criteria_insight = await _job_criteria(dataset, criteria, config)
    criteria_text = criteria_insight.content()
    checks = [
        check for chapter in parse_checklist(_checklist(criteria_text, "applicant")).chapters
        for check in chapter.checks
    ]
    await persons_in_dataset(dataset)
    people = await person_profile_as_person_objects(dataset)
    if not people:
        raise ValueError("No applicants found. Review the persons-in-dataset roster.")
    results = [criteria_insight]
    assessed: list[ApplicantAssessment] = []
    failures = []
    for person in people:
        try:
            item = await _assess_person(dataset, person, criteria_text, checks, config)
            assessed.append(item)
            results.extend([item.audit, item.report])
        except Exception as error:
            logger.exception("[%s] Applicant assessment failed: %s", dataset, person.display_name)
            failures.append(f"{person.display_name}: {error}")
    if failures:
        raise RuntimeError("Recruiting incomplete; successful assessments saved. " + "; ".join(failures))
    overview = await _build_overview(dataset, criteria_text, checks, assessed, config)
    return [*results, overview]

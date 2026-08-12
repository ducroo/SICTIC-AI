from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from lib.insights import InsightFile, insight_model_slug
from lib.slugify import slugify
from lib.storage import get_storage
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location, list_all_dataset_names
from skills.config_load.config_load import (
    config_key as serialize_config_key,
    config_load,
)


@dataclass(frozen=True)
class InsightMigrationResult:
    candidates: int = 0
    adopted: int = 0
    manual: int = 0
    skipped: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)


def _known_skills(config: dict) -> list[str]:
    configured = {slugify(key) for key in config}
    configured.update(
        {
            "advocates",
            "batch-audit",
            "dd-checks",
            "expert-search",
            "investor-profile",
            "person-profile",
            "persons-in-dataset",
            "potential-investors",
            "startup-profile",
            "suggested-startups",
            "team-profile",
        }
    )
    return sorted(configured, key=len, reverse=True)


def _parse_insight(
    dataset: str,
    relative_path: str,
    config: dict,
) -> tuple[str, str, str, bool] | None:
    path = PurePosixPath(relative_path)
    model = insight_model_slug(path.name)
    if model is None:
        return None

    stem_without_model = path.stem[: -(len(model) + 1)]
    if len(path.parts) > 1:
        return path.parts[-2], stem_without_model, model, True

    for skill in _known_skills(config):
        prefix = f"{skill}-"
        if stem_without_model.startswith(prefix):
            return skill, stem_without_model[len(prefix) :], model, False
    return None


def _person_name(content: str) -> str | None:
    for line in content.splitlines()[:5]:
        if line.lower().startswith("full-name:"):
            return line.split(":", 1)[1].strip() or None
    return None


def _config_key(
    skill: str,
    dataset: str,
    identifier: str,
    content: str,
    config: dict,
) -> str | None:
    key = skill.replace("-", "_")
    section = config.get(key, {})

    if skill == "person-profile":
        name = _person_name(content)
        if not name:
            return None
        query = section.get("query", "").replace("{{name}}", name)
        return query + section.get("llm_instructions", "")
    if skill == "team-profile":
        return (
            str(section.get("resume_queries", ""))
            + section.get("team_assessment_prompt", "").replace(
                "{{startupname}}",
                dataset,
            )
            + section.get("linkedin_classification_prompt", "")
        )
    if skill in {"expert-search", "potential-investors"}:
        return section.get("objective")
    if skill == "suggested-startups":
        return serialize_config_key(section)
    if skill == "investor-profile":
        return "compose person profile with investment track record"
    if skill == "dd-checks":
        dd = config.get("dd_checks", {})
        checklists = dd.get("checklists", {})
        return (
            dd.get("industry_type_query", "")
            + dd.get("industry_type_llm_instructions", "")
            + config.get("batch_audit", {}).get("llm_instructions", "")
            + "\n".join(f"{key}:{value}" for key, value in sorted(checklists.items()))
        )
    if skill == "submission-ready":
        submission = config.get("submission_ready", {})
        return "\n\n".join(
            str(submission.get(key, ""))
            for key in ("policy", "checklist", "llm_instructions")
        )
    if skill == "batch-audit":
        checklists = config.get("dd_checks", {}).get("checklists", {})
        checklist = next(
            (
                value
                for value in checklists.values()
                if slugify(value.splitlines()[0].lstrip("#").strip()) == identifier
            ),
            None,
        )
        if checklist:
            return checklist + config.get("batch_audit", {}).get(
                "llm_instructions",
                "",
            )
        return None
    if skill == "advocates":
        return None
    if isinstance(section, dict):
        query = section.get("query")
        instructions = section.get("llm_instructions")
        if query is not None and instructions is not None:
            return query + instructions
    return None


def _source_datasets(skill: str, dataset: str) -> list[str] | None:
    if skill in {"expert-search", "potential-investors"}:
        return ["sictic-members-investor-profile", dataset]
    if skill == "advocates":
        return ["sictic-members-investor-profile"]
    if skill == "suggested-startups":
        return None
    return [dataset]


def migrate_insight_manifests(*, apply: bool = False) -> InsightMigrationResult:
    storage = get_storage()
    config = config_load()
    candidates = adopted = manual = skipped = 0
    skipped_by_reason: dict[str, int] = {}
    datasets = list_all_dataset_names()

    for dataset in datasets:
        location = dataset_location(dataset)
        ingestion = IngestionManifest.load(storage, location.parsed_rel)
        if not ingestion.indexed_dataset_revision:
            ingestion.update_indexed_dataset_revision()
            if apply:
                ingestion.save()

    for dataset in datasets:
        location = dataset_location(dataset)
        for relative_path, _mtime in storage.list_with_mtime(
            location.insights_rel,
            recursive=True,
        ):
            if not relative_path.endswith(".md"):
                continue
            candidates += 1
            parsed = _parse_insight(dataset, relative_path, config)
            if parsed is None:
                skipped += 1
                skipped_by_reason["unrecognized-filename"] = (
                    skipped_by_reason.get("unrecognized-filename", 0) + 1
                )
                continue
            skill, identifier, model, subdir = parsed
            if model == "manual":
                manual += 1
                continue

            content = storage.read_text(f"{location.insights_rel}/{relative_path}")
            config_key = _config_key(
                skill,
                location.slug,
                identifier,
                content,
                config,
            )
            source_datasets = _source_datasets(skill, location.slug)
            if config_key is None or source_datasets is None:
                skipped += 1
                reason = f"dynamic-or-unknown:{skill}"
                skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
                continue

            insight = InsightFile(
                dataset=location.slug,
                skill=skill,
                model=model,
                identifier=identifier,
                subdir=subdir,
                source_datasets=source_datasets,
                config_key=config_key,
            )
            if apply:
                insight.save(content)
            adopted += 1

    return InsightMigrationResult(
        candidates=candidates,
        adopted=adopted,
        manual=manual,
        skipped=skipped,
        skipped_by_reason=skipped_by_reason,
    )

"""Canonical InsightFile construction and JSON reading for captable_build."""
from __future__ import annotations

import json
from datetime import date

from lib.captable.data import TOOL_VERSION
from lib.infrastructure.configuration import config_cache_key, load_repository_config

from lib.insights import InsightFile
from lib.model_config import llm_model


def build_insight(dataset: str, identifier: str, config_key: str = "") -> InsightFile:
    return InsightFile(dataset, "captable_build", llm_model(), identifier=identifier,
        subdir=True, extension="json", source_datasets=[dataset], config_key=config_key)


def read_build_insight(insight: InsightFile) -> dict:
    data = json.loads(insight.content())
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {insight.path}")
    if data.get("failures") or data.get("convertible_failures"):
        raise ValueError(f"Incomplete extraction in {insight.path}; repair the manual input or rerun captable_build.")
    return data


def configured_build_insight(dataset: str, identifier: str, *inputs: InsightFile) -> InsightFile:
    """Use identical dependency keys when generating and reading build artifacts."""
    config = load_repository_config("captable_build")
    keys = {
        "classification": ("classification_prompt", "classification_response_schema", "classification_settings"),
        "loan-extraction": ("cla_extraction_prompt", "cla_extraction_base_schema", "cla_terms"),
        "table-extraction": ("captable_extraction_prompt", "captable_extraction_response_schema", "register_extraction_prompt", "register_extraction_response_schema", "pool_extraction_prompt", "pool_extraction_response_schema"),
    }
    if identifier == "consolidated":
        key = config_cache_key(TOOL_VERSION, config["assessment_rules"], str(date.today()),
                               *(item.content() for item in inputs))
    else:
        key = config_cache_key(TOOL_VERSION, {name: config[name] for name in keys[identifier]},
                               *(item.content() for item in inputs))
    return build_insight(dataset, identifier, key)


def select_consolidated(dataset: str) -> InsightFile:
    """Read reusable consolidated data and dependencies without generating anything."""
    preferred = build_insight(dataset, "consolidated").find(selection="any")
    if preferred is not None and preferred.model == "manual":
        read_build_insight(preferred)
        return preferred

    def select(identifier: str, *inputs: InsightFile) -> InsightFile:
        insight = configured_build_insight(dataset, identifier, *inputs).find(selection="reusable")
        if insight is None:
            raise ValueError(f"No consolidated cap-table insight with reusable {identifier} for {dataset!r}; run captable_build first.")
        read_build_insight(insight)
        return insight

    classification = select("classification")
    loans = select("loan-extraction", classification)
    tables = select("table-extraction", classification)
    return select("consolidated", classification, loans, tables)

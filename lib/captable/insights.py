"""Canonical InsightFile construction and JSON reading for captable_build."""
from __future__ import annotations

import json

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


def select_consolidated(dataset: str) -> InsightFile:
    insight = build_insight(dataset, "consolidated").find(selection="any")
    if insight is None:
        raise ValueError(f"No consolidated cap-table insight for {dataset!r}; run captable_build first.")
    read_build_insight(insight)
    return insight

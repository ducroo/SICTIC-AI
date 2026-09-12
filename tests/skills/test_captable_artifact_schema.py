"""Stored/build artifact validation reuses extraction schemas and shared checks."""
from copy import deepcopy
import json

import pytest

from lib.captable.insights import build_insight, read_build_insight
from lib.captable.schema import build_artifact_schema, validate_build_artifact
from lib.infrastructure.ai_text_generation.json import validate_schema
from tests.skills.test_captable_build import (
    _captable_extraction, _complete_cla, _consolidated_artifact,
    _install_dataset, _patched_build,
)


def _artifacts():
    table = {**_captable_extraction("captable.md"), "dataset": "schema-co"}
    loan = _complete_cla("schema-co")
    return {
        "classification": {"dataset": "schema-co", "documents": [{
            "filename": "captable.md", "document_class": "current_cap_table",
            "confidence": 95, "as_of_date": None, "language": "en", "rationale": "Fixture",
        }]},
        "loan-extraction": {"dataset": "schema-co", "clas": [loan], "failures": []},
        "table-extraction": {
            "dataset": "schema-co", "captable": table, "captable_versions": [table],
            "register": None, "pool_documents": [], "failures": [],
        },
        "consolidated": _consolidated_artifact("schema-co", captable=table, loans=[loan]),
    }


@pytest.mark.parametrize("identifier", ["classification", "loan-extraction", "table-extraction", "consolidated"])
def test_roundtrip_all_artifacts_and_reject_missing_fields(mock_env, identifier):
    _install_dataset("schema-co", "Fixture")
    data = _artifacts()[identifier]
    validate_schema(build_artifact_schema(identifier))
    validate_build_artifact(data, identifier)
    insight = build_insight("schema-co", identifier)
    insight.save(json.dumps(data))
    assert read_build_insight(insight) == data
    del data["dataset"]
    insight.save(json.dumps(data))
    with pytest.raises(ValueError, match="dataset.*required"):
        read_build_insight(insight)


@pytest.mark.parametrize(("identifier", "mutate"), [
    ("classification", lambda data: data["documents"][0].update(confidence=101)),
    ("classification", lambda data: data["documents"][0].update(document_class="invented")),
    ("loan-extraction", lambda data: data["clas"][0]["principal_total"].update(value="100")),
    ("loan-extraction", lambda data: data["clas"][0].pop("comments")),
    ("table-extraction", lambda data: data["captable"]["stakeholders"][0].pop("quote")),
    ("table-extraction", lambda data: data["captable_versions"][0].pop("document")),
    ("table-extraction", lambda data: data.update(register={})),
    ("table-extraction", lambda data: data.update(pool_documents=[{}])),
    ("consolidated", lambda data: data["aggregation"].update(executed_count="one")),
    ("consolidated", lambda data: data["convertibles"][0].update(status="invented")),
    ("consolidated", lambda data: data["totals"].update(diluted_total="a million")),
])
def test_rejects_invalid_nested_artifact_fields(identifier, mutate):
    data = deepcopy(_artifacts()[identifier])
    mutate(data)
    with pytest.raises(ValueError, match="does not match the schema"):
        validate_build_artifact(data, identifier)


@pytest.mark.parametrize(("identifier", "field"), [
    ("loan-extraction", "failures"),
    ("table-extraction", "failures"),
    ("consolidated", "convertible_failures"),
])
def test_failure_flags_are_rejected_by_schema(identifier, field):
    data = _artifacts()[identifier]
    data[field] = [{"document": "loan.pdf", "error": "provider unavailable"}]
    with pytest.raises(ValueError, match=field):
        validate_build_artifact(data, identifier)


def test_no_captable_is_valid_data_with_domain_findings(mock_env):
    """Missing ownership evidence must remain representable, not become a schema error."""
    from skills.captable_build.captable_build import _consolidate

    _install_dataset("schema-co", "Fixture")
    artifacts = _artifacts()
    artifacts["table-extraction"].update(captable=None, captable_versions=[])
    from lib.infrastructure.configuration import load_repository_config
    data = _consolidate(
        "schema-co", artifacts["classification"], artifacts["table-extraction"],
        artifacts["loan-extraction"], load_repository_config("captable_build", "assessment_rules"),
    )
    validate_build_artifact(data, "consolidated")
    assert data["share_classes"] == []
    assert any(row["check"] == "table_extraction" and row["status"] == "fail" for row in data["validation"])


@pytest.mark.asyncio
async def test_invalid_assembled_output_does_not_overwrite_success(mock_env, monkeypatch):
    from unittest.mock import AsyncMock

    build, _ = _patched_build(monkeypatch)
    _install_dataset("schema-co", "Fixture")
    [previous] = await build.captable_build("schema-co")
    classification = build_insight("schema-co", "classification")
    previous_data, previous_classification = previous.content(), classification.content()
    monkeypatch.setattr(build, "classify_documents", AsyncMock(return_value={"dataset": "schema-co"}))
    with pytest.raises(ValueError, match="documents.*required"):
        await build.captable_build("schema-co", fresh=True)
    assert previous.content() == previous_data
    assert classification.content() == previous_classification


def test_artifact_schemas_do_not_mutate_generation_schemas():
    from lib.infrastructure.configuration import load_repository_config

    config = load_repository_config("captable_build")
    original = deepcopy(config)
    for identifier in _artifacts():
        build_artifact_schema(identifier)
    assert config == original


def test_artifacts_follow_new_configured_cla_terms(monkeypatch):
    from lib.captable import schema as module
    from lib.infrastructure.configuration import load_repository_config

    config = deepcopy(load_repository_config("captable_build"))
    config["cla_terms"] += "\n### reporting_frequency (string)\nExtract the reporting frequency.\n"
    monkeypatch.setattr(module, "load_repository_config", lambda *_: config)
    data = _artifacts()["loan-extraction"]
    with pytest.raises(ValueError, match="reporting_frequency.*required"):
        validate_build_artifact(data, "loan-extraction")
    data["clas"][0]["reporting_frequency"] = {"value": "quarterly", "quote": "Quarterly reports"}
    validate_build_artifact(data, "loan-extraction")


@pytest.mark.asyncio
async def test_schema_configuration_changes_invalidate_stage_cache(mock_env, monkeypatch):
    from lib.captable import insights as module

    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build, calls = _patched_build(monkeypatch)
    _install_dataset("schema-co", "Fixture")
    await build.captable_build("schema-co")
    await build.captable_build("schema-co")
    assert calls == {"classify": 1, "captable": 1}
    original = module.load_repository_config
    def edited(*args):
        config = deepcopy(original(*args))
        config["artifact_schemas"]["table-extraction"]["description"] = "Changed artifact contract"
        return config
    monkeypatch.setattr(module, "load_repository_config", edited)
    await build.captable_build("schema-co")
    assert calls == {"classify": 2, "captable": 2}


def test_register_pool_and_executed_cla_consolidation(mock_env):
    from skills.captable_build.captable_build import _consolidate
    from lib.infrastructure.configuration import load_repository_config

    _install_dataset("schema-co", "Fixture")
    artifacts = _artifacts()
    tables = artifacts["table-extraction"]
    metadata = {"dataset": "schema-co", "as_of_date": {"value": None, "quote": None}, "assumptions": []}
    tables["register"] = {**metadata, "document": "register.md", "entries": []}
    tables["pool_documents"] = [{**metadata, "document": "pool.md", "pools": []}]
    loan = artifacts["loan-extraction"]["clas"][0]
    loan.update(status="executed", principal_total={"value": 100_000, "quote": "100,000"},
                principal_currency={"value": "CHF", "quote": "CHF"},
                maturity_date={"value": "2020-01-01", "quote": "1 January 2020"})
    validate_build_artifact(tables, "table-extraction")
    data = _consolidate(
        "schema-co", artifacts["classification"], tables, artifacts["loan-extraction"],
        load_repository_config("captable_build", "assessment_rules"),
    )
    validate_build_artifact(data, "consolidated")
    assert data["aggregation"]["executed_count"] == 1
    assert data["assessment"][0]["findings"]
    assert data["aggregation"]["maturity"][0]["status"] == "expired_check_for_conversion"

"""Fail-closed tests for the public glossary source and generated view."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_glossary_doc import (  # noqa: E402
    render,
    validate_rendered_document,
    validate_source,
)


SOURCE_PATH = REPO_ROOT / "config" / "glossary" / "glossary.json"
DOC_PATH = REPO_ROOT / "docs" / "GLOSSARY.md"


@pytest.fixture
def source() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def test_public_source_validates(source):
    validate_source(source)


@pytest.mark.parametrize("version", [0, 2, "1", None])
def test_unsupported_schema_version_fails(source, version):
    source["schema_version"] = version
    with pytest.raises(ValueError, match="schema version"):
        validate_source(source)


def test_duplicate_identifier_fails(source):
    source["metric_contracts"][0]["id"] = source["terms"][0]["id"]
    with pytest.raises(ValueError, match="duplicate"):
        validate_source(source)


def test_stale_public_reference_fails(source):
    source["terms"][0]["references"][0]["path"] = "config/does-not-exist.json"
    with pytest.raises(ValueError, match="stale public reference"):
        validate_source(source)


@pytest.mark.parametrize(
    "location",
    [
        (),
        ("terms", 0),
        ("terms", 0, "references", 0),
        ("metric_contracts", 0),
        ("metric_contracts", 0, "producer"),
    ],
)
def test_arbitrary_properties_are_rejected(source, location):
    target = source
    for key in location:
        target = target[key]
    target["unexpected_property"] = "not part of the public schema"
    with pytest.raises(ValueError, match="unsupported properties"):
        validate_source(source)


def test_non_textual_property_names_are_rejected(source):
    source[1] = "not a JSON schema property"
    with pytest.raises(ValueError, match="non-textual property"):
        validate_source(source)


def test_missing_required_property_is_rejected(source):
    del source["terms"][0]["definition"]
    with pytest.raises(ValueError, match="missing required properties"):
        validate_source(source)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", None),
        ("description", ""),
        ("description", "line\nbreak"),
        ("generated_document", 12),
    ],
)
def test_textual_values_are_validated(source, field, value):
    source[field] = value
    with pytest.raises(ValueError):
        validate_source(source)


@pytest.mark.parametrize(
    "path",
    [
        "../config/batch_audit/audit_schema.json",
        "config/../lib/batch_audit/schema.py",
        "config/../../lib/batch_audit/schema.py",
        "/etc/passwd",
        "C:/outside/repository.py",
        r"\\server\share\outside.py",
        "other/file.py",
    ],
)
def test_reference_path_traversal_and_absolute_paths_fail(source, path):
    source["terms"][0]["references"][0]["path"] = path
    with pytest.raises(ValueError):
        validate_source(source)


def test_reference_separators_are_normalized_for_rendering(source):
    source["terms"][0]["references"][0]["path"] = (
        r"config\batch_audit\audit_schema.json"
    )
    document = render(source)
    assert "`config/batch_audit/audit_schema.json`" in document
    assert "\\" not in document


def test_unsupported_public_contract_fails(source):
    source["metric_contracts"][0]["contract"] = "metric-v99"
    with pytest.raises(ValueError, match="unsupported public contract"):
        validate_source(source)


def test_unsupported_contract_declaration_fails(source):
    source["supported_contracts"]["metric-v99"] = 99
    with pytest.raises(ValueError, match="unsupported properties"):
        validate_source(source)


def test_unsupported_endpoint_type_fails(source):
    source["metric_contracts"][0]["producer"]["type"] = ["opaque-public-type"]
    with pytest.raises(ValueError, match="unsupported metric endpoint type"):
        validate_source(source)


def test_metric_contract_requires_concrete_producer_and_consumer(source):
    source["metric_contracts"][0]["producer"]["type"] = []
    with pytest.raises(ValueError, match="concrete type"):
        validate_source(source)


def test_metric_contract_rejects_consumer_type_drift(source):
    source["metric_contracts"][0]["consumers"][0]["type"] = ["string", "null"]
    with pytest.raises(ValueError, match="type mismatch"):
        validate_source(source)


def test_metric_contract_rejects_producer_consumer_shape_drift(source):
    source["metric_contracts"][0]["consumers"][0]["path"] = "different.path"
    with pytest.raises(ValueError, match="path mismatch"):
        validate_source(source)


def test_rendered_document_requires_clean_text():
    with pytest.raises(ValueError):
        validate_rendered_document("line\x00break")


def test_generated_document_has_no_drift(source):
    validate_source(source)
    assert DOC_PATH.read_text(encoding="utf-8") == render(source)
    validate_rendered_document(DOC_PATH.read_text(encoding="utf-8"))


def test_render_is_deterministic(source):
    validate_source(source)
    assert render(source) == render(copy.deepcopy(source))

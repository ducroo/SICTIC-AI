import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from lib.assessments import AssessmentValidationError, build_assessment, canonical_json, render_assessment_markdown, validate_report


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "assessment_engine"
SCHEMAS = Path(__file__).resolve().parents[2] / "config" / "assessment_engine"


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _inputs():
    return (
        "synthetic-startup",
        _fixture("source_snapshot"),
        _fixture("methodology"),
        _fixture("classification"),
        _fixture("evidence"),
        _fixture("findings"),
    )


def _report(**overrides):
    values: list[Any] = list(_inputs())
    names = ["startup_id", "source_snapshot", "methodology", "classification", "evidence", "findings"]
    for name, value in overrides.items():
        values[names.index(name)] = value
    return build_assessment(*values)


def test_imports_are_public_core_only():
    prohibited = (
        "skills", "lib.storage", "lib.insights", "lib.model_config",
        "lib.infrastructure.ai_text_generation", "lib.people", "lib.datasets",
    )
    root = Path(__file__).resolve().parents[2] / "lib" / "assessments"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name == prefix or name.startswith(prefix + ".") for name in names for prefix in prohibited), path


def test_report_is_deterministic_and_has_distinct_cache_and_content_identity():
    first = _report()
    second = _report()
    assert first == second
    assert set(first["identity"]) == {"cache", "content"}
    assert first["identity"]["cache"]["key"] != first["identity"]["content"]["sha256"]
    assert first["identity"]["cache"]["components"]["finding_producer"]["config_sha256"]
    assert first["identity"]["content"]["components"]["selected_variants"] == {
        "requested": "moonlit", "selected": "general"
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda report: report.update(startup_id="synthetic-mutated-startup"),
        lambda report: report["source_snapshot"]["inventory"][0].update(sha256="c" * 64),
        lambda report: report["methodology"].update(id="synthetic-mutated-methodology"),
        lambda report: report["classification"].update(confidence="high"),
        lambda report: report["classification"]["provenance"].update(version="v2"),
        lambda report: report["evidence"][0].update(excerpt="Synthetic mutated evidence."),
        lambda report: report["finding_producer"].update(id="synthetic-mutated-producer"),
        lambda report: report["finding_producer"]["config"].update(mode="mutated"),
        lambda report: report["findings"][0].update(summary="Synthetic mutated finding."),
        lambda report: report["completeness"].update(complete=False),
        lambda report: report["sections"][0].update(summary="Synthetic mutated section."),
        lambda report: report["identity"]["content"]["components"].update(renderer="mutated-renderer"),
    ],
)
def test_any_persisted_content_mutation_is_rejected(mutator):
    report = _report()
    mutator(report)
    with pytest.raises(AssessmentValidationError, match="identity|reconstructed|normalized|complete|startup"):
        validate_report(report)


def test_recomputed_identity_digest_cannot_mask_component_mutation():
    report = _report()
    report["identity"]["cache"]["components"]["startup_id"] = "synthetic-mutated-startup"
    report["identity"]["cache"]["key"] = hashlib.sha256(
        canonical_json(report["identity"]["cache"]["components"]).encode("utf-8")
    ).hexdigest()
    with pytest.raises(AssessmentValidationError, match="identity"):
        validate_report(report)


def test_snapshot_is_closed_sorted_and_bound_to_startup():
    snapshot = copy.deepcopy(_fixture("source_snapshot"))
    snapshot["unknown"] = "not allowed"
    with pytest.raises(AssessmentValidationError, match="unknown keys"):
        _report(source_snapshot=snapshot)

    snapshot = copy.deepcopy(_fixture("source_snapshot"))
    snapshot["startup_id"] = "synthetic-other-startup"
    with pytest.raises(AssessmentValidationError, match="does not match"):
        _report(source_snapshot=snapshot)

    snapshot = copy.deepcopy(_fixture("source_snapshot"))
    snapshot["inventory"] = list(reversed(snapshot["inventory"]))
    report = _report(source_snapshot=snapshot)
    assert report["source_snapshot"]["inventory"] == sorted(snapshot["inventory"], key=lambda item: item["document_id"])
    assert report == _report()


@pytest.mark.parametrize("field, value", [("document_id", "unknown-document"), ("startup_id", "other-startup"), ("snapshot_id", "other-snapshot")])
def test_evidence_must_bind_to_snapshot_startup_and_inventory(field, value):
    evidence = copy.deepcopy(_fixture("evidence"))
    evidence[0][field] = value
    with pytest.raises(AssessmentValidationError, match="match|exist"):
        _report(evidence=evidence)


def test_evidence_reordering_is_canonical_and_arbitrary_source_fields_are_rejected():
    evidence = list(reversed(_fixture("evidence")))
    assert _report(evidence=evidence) == _report()
    evidence[0]["source"] = "arbitrary-source-field"
    with pytest.raises(AssessmentValidationError, match="unknown keys"):
        _report(evidence=evidence)


def test_evidence_reference_policy_rejects_or_allows_unreferenced_evidence():
    evidence = copy.deepcopy(_fixture("evidence"))
    evidence.append({
        "id": "synthetic-unreferenced-evidence",
        "snapshot_id": "synthetic-snapshot-001",
        "startup_id": "synthetic-startup",
        "document_id": "synthetic-document-01",
        "excerpt": "Synthetic evidence intentionally not used by a finding.",
    })
    with pytest.raises(AssessmentValidationError, match="unreferenced evidence"):
        _report(evidence=evidence)

    methodology = copy.deepcopy(_fixture("methodology"))
    methodology["policy"]["evidence_reference_policy"]["allow_unreferenced"] = True
    report = _report(methodology=methodology, evidence=evidence)
    assert report["completeness"]["complete"] is True


def test_explicit_producer_identity_and_config_are_required():
    findings = copy.deepcopy(_fixture("findings"))
    findings["producer"].pop("config")
    with pytest.raises(AssessmentValidationError, match="config"):
        _report(findings=findings)
    with pytest.raises(AssessmentValidationError, match="object"):
        _report(findings=list(findings["items"]))


def test_methodology_policy_and_classification_reasons_are_validated():
    methodology = copy.deepcopy(_fixture("methodology"))
    methodology["policy"]["unknown_is_incomplete"] = False
    with pytest.raises(AssessmentValidationError, match="unknown_is_incomplete"):
        _report(methodology=methodology)

    classification = copy.deepcopy(_fixture("classification"))
    classification["ambiguity_reason"] = None
    with pytest.raises(AssessmentValidationError, match="ambiguity_reason"):
        _report(classification=classification)

    classification = copy.deepcopy(_fixture("classification"))
    classification["variant"] = "moonlit"
    classification["uncertain"] = False
    classification["ambiguity_reason"] = None
    classification["override_reason"] = None
    classification["applicability"] = {
        "fable-moonlit-echo": {
            "state": "applicable", "basis": "evidence", "evidence_ids": ["synthetic-evidence-01"],
            "provenance": {"id": "synthetic-applicability", "version": "v1"},
        }
    }
    methodology = copy.deepcopy(_fixture("methodology"))
    methodology["policy"]["evidence_reference_policy"]["allow_unreferenced"] = True
    findings = {
        "producer": {"id": "synthetic-finding-producer", "version": "v1", "config": {}},
        "items": [{
            "id": "fable-moonlit-echo", "state": "supported", "summary": "Synthetic moonlit finding.",
            "evidence_ids": ["synthetic-evidence-01"], "follow_up_questions": [],
        }],
    }
    report = _report(methodology=methodology, classification=classification, findings=findings)
    assert report["classification"]["selected_variant"] == "moonlit"


def test_classification_evidence_and_provenance_are_snapshot_bound():
    classification = copy.deepcopy(_fixture("classification"))
    classification["evidence_ids"] = ["synthetic-not-bound"]
    with pytest.raises(AssessmentValidationError, match="classification.evidence_ids"):
        _report(classification=classification)

    classification = copy.deepcopy(_fixture("classification"))
    classification["provenance"] = {"id": "only-id"}
    with pytest.raises(AssessmentValidationError, match="classification.provenance"):
        _report(classification=classification)

    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"]["fable-team-echo"]["provenance"] = {"id": "only-id"}
    with pytest.raises(AssessmentValidationError, match="provenance"):
        _report(classification=classification)


def test_ungrounded_exclusion_is_rejected_and_valid_all_not_applicable_is_complete():
    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"]["fable-team-echo"]["evidence_ids"] = []
    with pytest.raises(AssessmentValidationError, match="snapshot-bound evidence"):
        _report(classification=classification)

    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"]["fable-team-echo"] = "not_applicable"
    with pytest.raises(AssessmentValidationError, match="object"):
        _report(classification=classification)

    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"]["fable-team-echo"] = {
        "state": "not_applicable", "basis": "evidence", "evidence_ids": [],
        "provenance": {"id": "synthetic-applicability", "version": "v1"},
    }
    with pytest.raises(AssessmentValidationError, match="snapshot-bound evidence"):
        _report(classification=classification)

    classification = copy.deepcopy(_fixture("classification"))
    evidence_ids = [item["id"] for item in _fixture("evidence")]
    for index, check_id in enumerate(classification["applicability"]):
        classification["applicability"][check_id] = {
            "state": "not_applicable",
            "basis": "evidence",
            "evidence_ids": [evidence_ids[index]],
            "provenance": {"id": "synthetic-applicability", "version": "v1"},
        }
    findings = copy.deepcopy(_fixture("findings"))
    findings["items"] = []
    report = _report(classification=classification, findings=findings)
    assert report["completeness"]["complete"] is True
    assert report["completeness"]["not_applicable_finding_ids"] == [
        "fable-team-echo", "fable-market-whisper", "fable-product-kite", "fable-docs-lantern"
    ]


def test_unknown_applicability_is_unresolved_and_incomplete():
    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"]["fable-product-kite"] = {
        "state": "unknown", "basis": "evidence", "evidence_ids": ["synthetic-evidence-03"],
        "provenance": {"id": "synthetic-applicability", "version": "v1"},
    }
    findings = copy.deepcopy(_fixture("findings"))
    findings["items"] = [item for item in findings["items"] if item["id"] != "fable-product-kite"]
    report = _report(classification=classification, findings=findings)
    assert report["completeness"]["complete"] is False
    assert report["completeness"]["unknown_finding_ids"] == ["fable-product-kite"]
    assert report["sections"][2]["state"] == "unknown"
    assert "Unknown:" in report["sections"][2]["summary"]


def test_not_applicable_and_missing_states_are_distinct():
    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"]["fable-product-kite"] = {
        "state": "not_applicable", "basis": "evidence", "evidence_ids": ["synthetic-evidence-03"],
        "provenance": {"id": "synthetic-applicability", "version": "v1"},
    }
    findings = copy.deepcopy(_fixture("findings"))
    findings["items"] = [item for item in findings["items"] if item["id"] != "fable-product-kite"]
    report = _report(classification=classification, findings=findings)
    assert report["sections"][2]["state"] == "not_applicable"

    findings = copy.deepcopy(_fixture("findings"))
    findings["items"] = [item for item in findings["items"] if item["id"] != "fable-product-kite"]
    report = _report(findings=findings)
    assert report["sections"][2]["state"] == "missing"
    assert report["completeness"]["complete"] is False


def test_no_general_fallback_remains_unassessed():
    methodology = copy.deepcopy(_fixture("methodology"))
    methodology["general_variant"] = None
    methodology["policy"]["evidence_reference_policy"]["allow_unreferenced"] = True
    classification = copy.deepcopy(_fixture("classification"))
    classification["applicability"] = {}
    report = _report(methodology=methodology, classification=classification, findings={
        "producer": {"id": "synthetic-finding-producer", "version": "v1", "config": {}}, "items": []
    })
    assert report["classification"]["selected_variant"] is None
    assert report["completeness"]["classification_unresolved"] is True
    assert report["completeness"]["complete"] is False
    assert all(section["state"] == "unknown" for section in report["sections"])


def test_rendered_checks_include_labels_states_evidence_and_questions_without_markdown_injection():
    findings = copy.deepcopy(_fixture("findings"))
    findings["items"][0]["summary"] = "Synthetic summary\n## injected heading [unsafe]"
    findings["items"][0]["follow_up_questions"] = ["Question with *markup* and `code`"]
    report = _report(findings=findings)
    markdown = render_assessment_markdown(report)
    assert "### Synthetic team signal (`fable-team-echo`)" in markdown
    assert "Applicability: applicable" in markdown
    assert "State: supported" in markdown
    assert "Follow-up questions:" in markdown
    assert "## injected heading" not in markdown
    assert "**Rating:**" not in markdown
    assert "recommendation" not in canonical_json(report).lower()
    assert '"decision":' not in canonical_json(report).lower()


def test_follow_up_questions_are_validated():
    findings = copy.deepcopy(_fixture("findings"))
    findings["items"][0]["follow_up_questions"] = ["same", "same"]
    with pytest.raises(AssessmentValidationError, match="duplicate questions"):
        _report(findings=findings)


def test_schemas_are_valid_and_runtime_output_validates_against_published_report_schema():
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    Draft202012Validator(json.loads((SCHEMAS / "methodology.schema.json").read_text())).validate(_fixture("methodology"))
    Draft202012Validator(json.loads((SCHEMAS / "classification.schema.json").read_text())).validate(_fixture("classification"))
    Draft202012Validator(json.loads((SCHEMAS / "source_snapshot.schema.json").read_text())).validate(_fixture("source_snapshot"))
    report = _report()
    schema = json.loads((SCHEMAS / "report.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(report))
    assert errors == []


def test_classification_schema_rejects_missing_evidence_ids():
    classification = _fixture("classification")
    classification.pop("evidence_ids")
    schema = json.loads((SCHEMAS / "classification.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(classification)


def test_golden_json_and_markdown_outputs_are_byte_stable():
    report = _report()
    json_bytes = canonical_json(report).encode("utf-8")
    markdown_bytes = render_assessment_markdown(report).encode("utf-8")
    assert hashlib.sha256(json_bytes).hexdigest() == "4333b740ee481447bf7c5cb7ce8f20140193f938e18a7cf2beaf3cf6a80e1d35"
    assert hashlib.sha256(markdown_bytes).hexdigest() == "ebc7773375bdb335be7e5bbda8322f634fb1bb717757fde4b51b4d2752a9e2b4"


def test_synthetic_fixtures_use_fictional_public_fixture_content():
    text = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURES.glob("*.json"))
    assert "synthetic-" in text
    assert all(path.name.endswith(".json") for path in FIXTURES.glob("*.json"))

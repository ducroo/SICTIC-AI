"""Clean-room, deterministic assessment contracts.

This module accepts already prepared, public-safe values only.  It never
discovers, loads, searches, stores, scores, or transmits startup material.
The persisted report contains enough normalized content to reconstruct both
its pre-execution cache identity and its post-execution content identity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator


CONTRACT_ID = "public-assessment-engine"
CONTRACT_VERSION = "v2"
ENGINE_ID = "deterministic-jury-assessment-core"
ENGINE_VERSION = "v2"
SCHEMA_ID = "assessment-engine-report-v2"
RENDERER_ID = "assessment-engine-markdown-v2"
SECTION_ORDER = ["Team", "Business opportunity", "Product", "Documentation"]
APPLICABILITY_STATES = ["applicable", "not_applicable", "unknown"]
FINDING_STATES = ["supported", "uncertain", "not_observed"]
SECTION_STATES = ["assessed", "missing", "unknown", "not_applicable"]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "config" / "assessment_engine"


class AssessmentValidationError(ValueError):
    """Raised when supplied assessment contract values are invalid."""


def _error(path: str, message: str) -> AssessmentValidationError:
    return AssessmentValidationError(f"{path}: {message}")


def _object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be an object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise _error(path, "object keys must be strings")
    return result


def _keys(
    value: dict[str, Any],
    *,
    path: str,
    required: set[str],
    allowed: set[str],
) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise _error(path, f"missing required keys: {', '.join(missing)}")
    if extra:
        raise _error(path, f"unknown keys: {', '.join(extra)}")


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(path, "must be a nonempty string")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise _error(path, "contains a control character")
    return value.strip()


def _startup_id(value: object, path: str = "startup_id") -> str:
    startup_id = _string(value, path)
    if startup_id in {".", ".."} or "/" in startup_id or "\\" in startup_id:
        raise _error(path, "must be an identifier, not a filesystem path")
    return startup_id


def _json_value(value: object, path: str = "value") -> object:
    """Validate that a value is JSON data with finite numbers only."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(path, "must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise _error(path, "object keys must be strings")
            result[key] = _json_value(child, f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_json_value(child, f"{path}[{index}]") for index, child in enumerate(value)]
    raise _error(path, f"contains unsupported value type {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Return stable compact JSON for a validated report or input value."""
    normalized = _json_value(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    path = SCHEMA_DIR / schema_name
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except (OSError, json.JSONDecodeError) as exc:
        raise AssessmentValidationError(f"schema {schema_name}: cannot load: {exc}") from exc


def _schema_validate(value: object, schema_name: str, path: str) -> None:
    errors = sorted(_validator(schema_name).iter_errors(cast(Any, value)), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path)
        suffix = f".{location}" if location else ""
        raise _error(path + suffix, error.message)


def _sha256(value: object, path: str) -> str:
    result = _string(value, path).lower()
    if not SHA256_RE.fullmatch(result):
        raise _error(path, "must be a lowercase SHA-256 digest")
    return result


def _source_snapshot(value: object, *, canonical: bool = False) -> dict[str, Any]:
    snapshot = _object(value, "source_snapshot")
    allowed = {"snapshot_id", "startup_id", "scope_id", "inventory"}
    _keys(snapshot, path="source_snapshot", required=allowed, allowed=allowed)
    normalized: dict[str, Any] = {
        "snapshot_id": _string(snapshot["snapshot_id"], "source_snapshot.snapshot_id"),
        "startup_id": _startup_id(snapshot["startup_id"], "source_snapshot.startup_id"),
        "scope_id": _string(snapshot["scope_id"], "source_snapshot.scope_id"),
    }
    inventory = snapshot["inventory"]
    if not isinstance(inventory, list):
        raise _error("source_snapshot.inventory", "must be an array")
    records = []
    seen: set[str] = set()
    for index, raw_record in enumerate(inventory):
        path = f"source_snapshot.inventory[{index}]"
        record = _object(raw_record, path)
        _keys(record, path=path, required={"document_id", "sha256"}, allowed={"document_id", "sha256"})
        document_id = _string(record["document_id"], f"{path}.document_id")
        if document_id in seen:
            raise _error("source_snapshot.inventory", f"duplicate document id: {document_id}")
        seen.add(document_id)
        records.append({"document_id": document_id, "sha256": _sha256(record["sha256"], f"{path}.sha256")})
    normalized["inventory"] = sorted(records, key=lambda record: record["document_id"])
    if canonical and inventory != normalized["inventory"]:
        raise _error("source_snapshot.inventory", "must be sorted by document_id")
    _schema_validate(normalized, "source_snapshot.schema.json", "source_snapshot")
    return normalized


def _policy(value: object, path: str) -> dict[str, Any]:
    policy = _object(value, path)
    allowed = {
        "classification_vocabulary",
        "confidence_vocabulary",
        "applicability_vocabulary",
        "evidence_reference_policy",
        "applicability_decision_policy",
        "unknown_is_incomplete",
        "ambiguity_reason_required",
        "override_reason_required",
    }
    _keys(policy, path=path, required=allowed, allowed=allowed)
    vocabulary = _object(policy["classification_vocabulary"], f"{path}.classification_vocabulary")
    normalized_vocabulary = {}
    for label, variant in vocabulary.items():
        normalized_vocabulary[_string(label, f"{path}.classification_vocabulary.key")] = _string(
            variant, f"{path}.classification_vocabulary.{label}"
        )
    confidence = policy["confidence_vocabulary"]
    if not isinstance(confidence, list) or not confidence:
        raise _error(f"{path}.confidence_vocabulary", "must be a nonempty string array")
    normalized_confidence = [_string(item, f"{path}.confidence_vocabulary[{i}]") for i, item in enumerate(confidence)]
    if len(set(normalized_confidence)) != len(normalized_confidence):
        raise _error(f"{path}.confidence_vocabulary", "must not contain duplicates")
    applicability = policy["applicability_vocabulary"]
    if applicability != APPLICABILITY_STATES:
        raise _error(f"{path}.applicability_vocabulary", f"must equal {APPLICABILITY_STATES}")
    evidence_policy = _object(policy["evidence_reference_policy"], f"{path}.evidence_reference_policy")
    _keys(evidence_policy, path=f"{path}.evidence_reference_policy", required={"required", "allow_unreferenced"}, allowed={"required", "allow_unreferenced"})
    if evidence_policy["required"] is not True or not isinstance(evidence_policy["allow_unreferenced"], bool):
        raise _error(f"{path}.evidence_reference_policy", "requires true evidence references and a boolean allow_unreferenced")
    decision_policy = _object(policy["applicability_decision_policy"], f"{path}.applicability_decision_policy")
    _keys(
        decision_policy,
        path=f"{path}.applicability_decision_policy",
        required={"basis_vocabulary", "evidence_required_for_non_default", "evidence_required_for_exclusion", "provenance_required"},
        allowed={"basis_vocabulary", "evidence_required_for_non_default", "evidence_required_for_exclusion", "provenance_required"},
    )
    bases = decision_policy["basis_vocabulary"]
    if not isinstance(bases, list) or not bases:
        raise _error(f"{path}.applicability_decision_policy.basis_vocabulary", "must be a nonempty string array")
    normalized_bases = [_string(item, f"{path}.applicability_decision_policy.basis_vocabulary[{i}]") for i, item in enumerate(bases)]
    if len(set(normalized_bases)) != len(normalized_bases):
        raise _error(f"{path}.applicability_decision_policy.basis_vocabulary", "must not contain duplicates")
    for key in ("evidence_required_for_non_default", "evidence_required_for_exclusion", "provenance_required"):
        if decision_policy[key] is not True:
            raise _error(f"{path}.applicability_decision_policy.{key}", "must be true")
    for key in ("unknown_is_incomplete", "ambiguity_reason_required", "override_reason_required"):
        if not isinstance(policy[key], bool):
            raise _error(f"{path}.{key}", "must be boolean")
    if not policy["unknown_is_incomplete"]:
        raise _error(f"{path}.unknown_is_incomplete", "must be true for deterministic unresolved policy")
    return {
        "classification_vocabulary": normalized_vocabulary,
        "confidence_vocabulary": normalized_confidence,
        "applicability_vocabulary": list(APPLICABILITY_STATES),
        "evidence_reference_policy": {
            "required": True,
            "allow_unreferenced": evidence_policy["allow_unreferenced"],
        },
        "applicability_decision_policy": {
            "basis_vocabulary": normalized_bases,
            "evidence_required_for_non_default": True,
            "evidence_required_for_exclusion": True,
            "provenance_required": True,
        },
        "unknown_is_incomplete": True,
        "ambiguity_reason_required": policy["ambiguity_reason_required"],
        "override_reason_required": policy["override_reason_required"],
    }


def _methodology(value: object, *, canonical: bool = False) -> dict[str, Any]:
    methodology = _object(value, "methodology")
    allowed = {"id", "version", "general_variant", "policy", "applicability_rules", "variants"}
    _keys(methodology, path="methodology", required=allowed, allowed=allowed)
    general_variant = methodology["general_variant"]
    if general_variant is not None:
        general_variant = _string(general_variant, "methodology.general_variant")
    variants = _object(methodology["variants"], "methodology.variants")
    if not variants:
        raise _error("methodology.variants", "must contain at least one variant")
    normalized_variants: dict[str, Any] = {}
    all_check_ids: set[str] = set()
    for variant_name, raw_variant in variants.items():
        variant_name = _string(variant_name, "methodology.variants.key")
        path = f"methodology.variants.{variant_name}"
        variant = _object(raw_variant, path)
        _keys(variant, path=path, required={"checks"}, allowed={"checks"})
        checks = variant["checks"]
        if not isinstance(checks, list):
            raise _error(f"{path}.checks", "must be an array")
        normalized_checks = []
        seen_ids: set[str] = set()
        for index, raw_check in enumerate(checks):
            check_path = f"{path}.checks[{index}]"
            check = _object(raw_check, check_path)
            _keys(check, path=check_path, required={"id", "section", "label"}, allowed={"id", "section", "label"})
            check_id = _string(check["id"], f"{check_path}.id")
            section = _string(check["section"], f"{check_path}.section")
            if section not in SECTION_ORDER:
                raise _error(f"{check_path}.section", f"unsupported section: {section}")
            label = _string(check["label"], f"{check_path}.label")
            if check_id in seen_ids or check_id in all_check_ids:
                raise _error(f"{path}.checks", f"duplicate check id: {check_id}")
            seen_ids.add(check_id)
            all_check_ids.add(check_id)
            normalized_checks.append({"id": check_id, "section": section, "label": label})
        normalized_variants[variant_name] = {"checks": normalized_checks}
    if general_variant is not None and general_variant not in normalized_variants:
        raise _error("methodology.general_variant", f"does not name a configured variant: {general_variant}")
    policy = _policy(methodology["policy"], "methodology.policy")
    for label, variant_name in policy["classification_vocabulary"].items():
        if variant_name not in normalized_variants:
            raise _error(
                f"methodology.policy.classification_vocabulary.{label}",
                f"does not name a configured variant: {variant_name}",
            )
    if general_variant is not None and general_variant not in policy["classification_vocabulary"].values():
        raise _error("methodology.general_variant", "must be represented in classification vocabulary")
    raw_rules = _object(methodology["applicability_rules"], "methodology.applicability_rules")
    if set(raw_rules) != all_check_ids:
        missing = sorted(all_check_ids - set(raw_rules))
        extra = sorted(set(raw_rules) - all_check_ids)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise _error("methodology.applicability_rules", "; ".join(details))
    normalized_rules = {}
    for check_id in sorted(all_check_ids):
        path = f"methodology.applicability_rules.{check_id}"
        rule = _object(raw_rules[check_id], path)
        _keys(rule, path=path, required={"allowed_states", "default_state"}, allowed={"allowed_states", "default_state"})
        allowed_states = rule["allowed_states"]
        if not isinstance(allowed_states, list) or not allowed_states:
            raise _error(f"{path}.allowed_states", "must be a nonempty array")
        states = [_string(state, f"{path}.allowed_states[{i}]") for i, state in enumerate(allowed_states)]
        if len(set(states)) != len(states) or any(state not in APPLICABILITY_STATES for state in states):
            raise _error(f"{path}.allowed_states", "contains invalid or duplicate applicability states")
        default_state = _string(rule["default_state"], f"{path}.default_state")
        if default_state not in states:
            raise _error(f"{path}.default_state", "must be included in allowed_states")
        normalized_rules[check_id] = {"allowed_states": states, "default_state": default_state}
    normalized = {
        "id": _string(methodology["id"], "methodology.id"),
        "version": _string(methodology["version"], "methodology.version"),
        "general_variant": general_variant,
        "policy": policy,
        "applicability_rules": normalized_rules,
        "variants": normalized_variants,
    }
    _schema_validate(normalized, "methodology.schema.json", "methodology")
    if canonical and methodology != normalized:
        raise _error("methodology", "persisted value is not normalized")
    return normalized


def _classification(
    value: object,
    methodology: dict[str, Any],
    evidence_ids: set[str],
    *,
    canonical: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    classification = _object(value, "classification")
    if not canonical:
        _schema_validate(classification, "classification.schema.json", "classification")
    input_allowed = {
        "label", "variant", "confidence", "uncertain", "ambiguity_reason", "override_reason",
        "provenance", "evidence_ids", "applicability",
    }
    report_allowed = {
        "label", "requested_variant", "selected_variant", "confidence", "uncertain",
        "ambiguity_reason", "override_reason", "provenance", "evidence_ids", "applicability",
        "applicability_decisions",
    }
    if "requested_variant" in classification or "selected_variant" in classification:
        _keys(classification, path="classification", required=report_allowed, allowed=report_allowed)
    else:
        _keys(classification, path="classification", required=input_allowed, allowed=input_allowed)
    policy = methodology["policy"]
    label = _string(classification["label"], "classification.label")
    vocabulary = policy["classification_vocabulary"]
    if label not in vocabulary:
        raise _error("classification.label", f"must be one of {sorted(vocabulary)}")
    confidence = _string(classification["confidence"], "classification.confidence")
    if confidence not in policy["confidence_vocabulary"]:
        raise _error("classification.confidence", f"must be one of {policy['confidence_vocabulary']}")
    uncertain = classification["uncertain"]
    if not isinstance(uncertain, bool):
        raise _error("classification.uncertain", "must be boolean")
    ambiguity_reason = classification["ambiguity_reason"]
    if ambiguity_reason is not None:
        ambiguity_reason = _string(ambiguity_reason, "classification.ambiguity_reason")
    if uncertain and policy["ambiguity_reason_required"] and ambiguity_reason is None:
        raise _error("classification.ambiguity_reason", "is required for uncertain classification")
    if not uncertain and ambiguity_reason is not None:
        raise _error("classification.ambiguity_reason", "must be null for certain classification")
    requested_variant = classification.get("requested_variant", classification.get("variant"))
    if requested_variant is not None:
        requested_variant = _string(requested_variant, "classification.variant")
        if requested_variant not in methodology["variants"]:
            raise _error("classification.variant", f"does not name a configured variant: {requested_variant}")
    expected_variant = vocabulary[label]
    override_reason = classification["override_reason"]
    if override_reason is not None:
        override_reason = _string(override_reason, "classification.override_reason")
    if requested_variant is not None and requested_variant != expected_variant:
        if policy["override_reason_required"] and override_reason is None:
            raise _error("classification.override_reason", "is required for a variant override")
    elif override_reason is not None:
        raise _error("classification.override_reason", "requires a variant override")
    if uncertain:
        selected_variant = methodology["general_variant"]
    else:
        selected_variant = requested_variant or expected_variant
        if selected_variant != expected_variant and policy["override_reason_required"] and override_reason is None:
            raise _error("classification.override_reason", "is required for a variant override")
    provenance = _object(classification["provenance"], "classification.provenance")
    _keys(provenance, path="classification.provenance", required={"id", "version"}, allowed={"id", "version"})
    normalized_provenance = {
        "id": _string(provenance["id"], "classification.provenance.id"),
        "version": _string(provenance["version"], "classification.provenance.version"),
    }
    classification_evidence = classification["evidence_ids"]
    if not isinstance(classification_evidence, list) or not classification_evidence:
        raise _error("classification.evidence_ids", "must contain at least one evidence id")
    normalized_classification_evidence = sorted(
        {_string(item, "classification.evidence_ids") for item in classification_evidence}
    )
    if len(normalized_classification_evidence) != len(classification_evidence):
        raise _error("classification.evidence_ids", "must not contain duplicates")
    missing_classification_evidence = sorted(set(normalized_classification_evidence) - evidence_ids)
    if missing_classification_evidence:
        raise _error(
            "classification.evidence_ids",
            f"does not exist in evidence: {', '.join(missing_classification_evidence)}",
        )
    raw_applicability = _object(classification["applicability"], "classification.applicability")
    persisted_decisions = classification.get("applicability_decisions")
    if canonical:
        if not isinstance(persisted_decisions, Mapping):
            raise _error("classification.applicability_decisions", "must be an object")
        persisted_decisions = _object(persisted_decisions, "classification.applicability_decisions")
    checks = [] if selected_variant is None else methodology["variants"][selected_variant]["checks"]
    check_ids = {check["id"] for check in checks}
    extra = sorted(set(raw_applicability) - check_ids)
    if extra:
        raise _error("classification.applicability", f"unknown check ids: {', '.join(extra)}")
    normalized_applicability = {}
    normalized_decisions = {}
    decision_policy = methodology["policy"]["applicability_decision_policy"]
    allowed_bases = decision_policy["basis_vocabulary"]
    for check in checks:
        check_id = check["id"]
        rule = methodology["applicability_rules"][check_id]
        raw_decision = (
            persisted_decisions.get(check_id)
            if canonical and isinstance(persisted_decisions, Mapping)
            else raw_applicability.get(check_id)
        )
        if raw_decision is None:
            if canonical:
                raise _error(f"classification.applicability.{check_id}", "is missing persisted decision")
            state = rule["default_state"]
            if state == "not_applicable":
                raise _error(
                    f"classification.applicability.{check_id}",
                    "requires an explicit evidence-backed exclusion decision",
                )
            decision = {
                "state": state,
                "basis": "default",
                "evidence_ids": [],
                "provenance": {"id": "methodology-default", "version": methodology["version"]},
            }
        else:
            decision = _object(raw_decision, f"classification.applicability.{check_id}")
            decision_allowed = {"state", "basis", "evidence_ids", "provenance"}
            _keys(
                decision,
                path=f"classification.applicability.{check_id}",
                required=decision_allowed,
                allowed=decision_allowed,
            )
            state = _string(decision["state"], f"classification.applicability.{check_id}.state")
            basis = _string(decision["basis"], f"classification.applicability.{check_id}.basis")
            if basis not in allowed_bases:
                raise _error(
                    f"classification.applicability.{check_id}.basis",
                    f"must be one of {allowed_bases}",
                )
            if basis == "default" and (state != rule["default_state"] or state == "not_applicable"):
                raise _error(
                    f"classification.applicability.{check_id}.basis",
                    "default basis must use the configured default state",
                )
            decision_evidence = decision["evidence_ids"]
            if not isinstance(decision_evidence, list):
                raise _error(
                    f"classification.applicability.{check_id}.evidence_ids",
                    "must be an array",
                )
            normalized_decision_evidence = sorted(
                {_string(item, f"classification.applicability.{check_id}.evidence_ids") for item in decision_evidence}
            )
            if len(normalized_decision_evidence) != len(decision_evidence):
                raise _error(
                    f"classification.applicability.{check_id}.evidence_ids",
                    "must not contain duplicates",
                )
            missing_decision_evidence = sorted(set(normalized_decision_evidence) - evidence_ids)
            if missing_decision_evidence:
                raise _error(
                    f"classification.applicability.{check_id}.evidence_ids",
                    f"does not exist in evidence: {', '.join(missing_decision_evidence)}",
                )
            decision_provenance = _object(
                decision["provenance"],
                f"classification.applicability.{check_id}.provenance",
            )
            _keys(
                decision_provenance,
                path=f"classification.applicability.{check_id}.provenance",
                required={"id", "version"},
                allowed={"id", "version"},
            )
            normalized_decision = {
                "state": state,
                "basis": basis,
                "evidence_ids": normalized_decision_evidence,
                "provenance": {
                    "id": _string(decision_provenance["id"], f"classification.applicability.{check_id}.provenance.id"),
                    "version": _string(decision_provenance["version"], f"classification.applicability.{check_id}.provenance.version"),
                },
            }
            decision = normalized_decision
        if state not in rule["allowed_states"]:
            raise _error(f"classification.applicability.{check_id}", f"must be one of {rule['allowed_states']}")
        basis = decision["basis"]
        decision_evidence_ids = decision["evidence_ids"]
        requires_evidence = (
            (state != rule["default_state"] and decision_policy["evidence_required_for_non_default"])
            or (state == "not_applicable" and decision_policy["evidence_required_for_exclusion"])
            or basis == "evidence"
        )
        if requires_evidence and not decision_evidence_ids:
            raise _error(
                f"classification.applicability.{check_id}.evidence_ids",
                "must contain snapshot-bound evidence for a non-default or excluding decision",
            )
        normalized_applicability[check_id] = state
        normalized_decisions[check_id] = decision
    if selected_variant is None and raw_applicability:
        raise _error("classification.applicability", "must be empty without a configured general fallback")
    if canonical and set(persisted_decisions or {}) != check_ids:
        raise _error("classification.applicability_decisions", "must match selected variant checks")
    normalized = {
        "label": label,
        "requested_variant": requested_variant,
        "selected_variant": selected_variant,
        "confidence": confidence,
        "uncertain": uncertain,
        "ambiguity_reason": ambiguity_reason,
        "override_reason": override_reason,
        "provenance": normalized_provenance,
        "evidence_ids": normalized_classification_evidence,
        "applicability": normalized_applicability,
        "applicability_decisions": normalized_decisions,
    }
    if canonical and classification != normalized:
        raise _error("classification", "persisted value is not normalized")
    return normalized, checks


def _evidence(
    value: object,
    snapshot: dict[str, Any],
    startup_id: str,
    *,
    canonical: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _error("evidence", "must be an array")
    inventory_ids = {record["document_id"] for record in snapshot["inventory"]}
    normalized = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(value):
        path = f"evidence[{index}]"
        item = _object(raw_item, path)
        allowed = {"id", "snapshot_id", "startup_id", "document_id", "excerpt"}
        _keys(item, path=path, required=allowed, allowed=allowed)
        evidence_id = _string(item["id"], f"{path}.id")
        if evidence_id in seen_ids:
            raise _error("evidence", f"duplicate evidence id: {evidence_id}")
        seen_ids.add(evidence_id)
        item_snapshot = _string(item["snapshot_id"], f"{path}.snapshot_id")
        if item_snapshot != snapshot["snapshot_id"]:
            raise _error(f"{path}.snapshot_id", "does not match source_snapshot")
        item_startup = _startup_id(item["startup_id"], f"{path}.startup_id")
        if item_startup != startup_id or item_startup != snapshot["startup_id"]:
            raise _error(f"{path}.startup_id", "does not match startup/source_snapshot")
        document_id = _string(item["document_id"], f"{path}.document_id")
        if document_id not in inventory_ids:
            raise _error(f"{path}.document_id", "does not exist in source_snapshot.inventory")
        normalized.append({
            "id": evidence_id,
            "snapshot_id": item_snapshot,
            "startup_id": item_startup,
            "document_id": document_id,
            "excerpt": _string(item["excerpt"], f"{path}.excerpt"),
        })
    normalized.sort(key=lambda item: item["id"])
    if canonical and value != normalized:
        raise _error("evidence", "persisted value is not normalized by evidence id")
    return normalized


def _producer(value: object) -> dict[str, Any]:
    producer = _object(value, "findings.producer")
    _keys(producer, path="findings.producer", required={"id", "version", "config"}, allowed={"id", "version", "config"})
    config = _object(producer["config"], "findings.producer.config")
    _json_value(config, "findings.producer.config")
    return {
        "id": _string(producer["id"], "findings.producer.id"),
        "version": _string(producer["version"], "findings.producer.version"),
        "config": copy.deepcopy(config),
    }


def _questions(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise _error(path, "must be an array")
    result = []
    for index, item in enumerate(value):
        result.append(_string(item, f"{path}[{index}]"))
    if len(set(result)) != len(result):
        raise _error(path, "must not contain duplicate questions")
    return result


def _findings(
    value: object,
    *,
    checks: list[dict[str, Any]],
    evidence_ids: set[str],
    applicability: dict[str, str],
    allow_unreferenced: bool,
    additional_referenced_evidence_ids: set[str],
    canonical: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _object(value, "findings")
    _keys(raw, path="findings", required={"producer", "items"}, allowed={"producer", "items"})
    producer = _producer(raw["producer"])
    items = raw["items"]
    if not isinstance(items, list):
        raise _error("findings.items", "must be an array")
    checks_by_id = {check["id"]: check for check in checks}
    check_order = {check["id"]: index for index, check in enumerate(checks)}
    normalized_by_id: dict[str, dict[str, Any]] = {}
    for index, raw_item in enumerate(items):
        path = f"findings.items[{index}]"
        item = _object(raw_item, path)
        input_keys = {"id", "state", "summary", "evidence_ids", "follow_up_questions"}
        report_keys = input_keys | {"label", "section", "applicability"}
        persisted = "label" in item or "section" in item or "applicability" in item
        _keys(item, path=path, required=report_keys if persisted else input_keys, allowed=report_keys if persisted else input_keys)
        finding_id = _string(item["id"], f"{path}.id")
        if finding_id in normalized_by_id:
            raise _error("findings.items", f"duplicate finding id: {finding_id}")
        if finding_id not in checks_by_id:
            raise _error(f"{path}.id", f"extra finding is not in methodology: {finding_id}")
        if applicability[finding_id] != "applicable":
            raise _error(f"{path}.id", f"finding is not applicable (state: {applicability[finding_id]})")
        state = _string(item["state"], f"{path}.state")
        if state not in FINDING_STATES:
            raise _error(f"{path}.state", f"must be one of {FINDING_STATES}")
        refs = item["evidence_ids"]
        if not isinstance(refs, list) or not refs:
            raise _error(f"{path}.evidence_ids", "must contain at least one evidence id")
        normalized_refs = sorted({_string(ref, f"{path}.evidence_ids") for ref in refs})
        if len(normalized_refs) != len(refs):
            raise _error(f"{path}.evidence_ids", "must not contain duplicate evidence ids")
        missing = sorted(set(normalized_refs) - evidence_ids)
        if missing:
            raise _error(f"{path}.evidence_ids", f"does not exist in evidence: {', '.join(missing)}")
        normalized_by_id[finding_id] = {
            "id": finding_id,
            "label": checks_by_id[finding_id]["label"],
            "section": checks_by_id[finding_id]["section"],
            "applicability": applicability[finding_id],
            "state": state,
            "summary": _string(item["summary"], f"{path}.summary"),
            "evidence_ids": normalized_refs,
            "follow_up_questions": _questions(item["follow_up_questions"], f"{path}.follow_up_questions"),
        }
        if persisted:
            for field in ("label", "section", "applicability"):
                if item[field] != normalized_by_id[finding_id][field]:
                    raise _error(f"{path}.{field}", "does not match methodology/applicability")
    normalized = [normalized_by_id[key] for key in sorted(normalized_by_id, key=check_order.__getitem__)]
    if not allow_unreferenced:
        referenced_ids = additional_referenced_evidence_ids | {
            evidence_id for finding in normalized for evidence_id in finding["evidence_ids"]
        }
        unreferenced_ids = sorted(evidence_ids - referenced_ids)
        if unreferenced_ids:
            raise _error(
                "evidence",
                f"contains unreferenced evidence while policy disallows it: {', '.join(unreferenced_ids)}",
            )
    if canonical and items != normalized:
        raise _error("findings.items", "persisted value is not normalized by methodology check order")
    return producer, normalized


def _section_state(checks: list[dict[str, Any]]) -> str:
    states = {check["state"] for check in checks}
    if "unknown" in states:
        return "unknown"
    if "missing" in states:
        return "missing"
    if states and states <= {"not_applicable"}:
        return "not_applicable"
    return "assessed" if checks else "unknown"


def _build_sections(
    methodology_checks: list[dict[str, Any]],
    classification: dict[str, Any],
    findings: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    finding_by_id = {finding["id"]: finding for finding in findings}
    sections = []
    for section_name in SECTION_ORDER:
        checks = []
        for method_check in methodology_checks:
            if method_check["section"] != section_name:
                continue
            check_id = method_check["id"]
            applicability = classification["applicability"].get(check_id, "unknown")
            finding = finding_by_id.get(check_id)
            if finding is not None:
                state = finding["state"]
                summary = finding["summary"]
                evidence_ids = finding["evidence_ids"]
                questions = finding["follow_up_questions"]
            elif applicability == "not_applicable":
                state = "not_applicable"
                summary = "This check is not applicable under the resolved methodology policy."
                evidence_ids = []
                questions = []
            elif applicability == "unknown":
                state = "unknown"
                summary = "Applicability remains unknown; no finding was produced."
                evidence_ids = []
                questions = []
            else:
                state = "missing"
                summary = "Applicable finding material is missing."
                evidence_ids = []
                questions = []
            checks.append({
                "id": check_id,
                "label": method_check["label"],
                "applicability": applicability,
                "state": state,
                "summary": summary,
                "evidence_ids": evidence_ids,
                "evidence": [evidence_by_id[item]["excerpt"] for item in evidence_ids],
                "follow_up_questions": questions,
            })
        state = _section_state(checks)
        if state == "unknown":
            summary = "Unknown: one or more checks remain unresolved."
        elif state == "missing":
            summary = "Missing: one or more applicable findings were not supplied."
        elif state == "not_applicable":
            summary = "Not applicable: all checks in this section are excluded by policy."
        else:
            summary = "Assessed: deterministic finding material is supplied for this section."
        questions = []
        for check in checks:
            for question in check["follow_up_questions"]:
                if question not in questions:
                    questions.append(question)
        sections.append({
            "name": section_name,
            "state": state,
            "summary": summary,
            "checks": checks,
            "jury_questions": questions,
            "finding_ids": [check["id"] for check in checks if check["state"] in FINDING_STATES],
            "evidence_ids": [evidence_id for check in checks for evidence_id in check["evidence_ids"] if evidence_id],
            "evidence": [evidence_by_id[evidence_id]["excerpt"] for check in checks for evidence_id in check["evidence_ids"]],
        })
    return sections


def _completeness(
    checks: list[dict[str, Any]],
    classification: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    applicability = classification["applicability"]
    applicable = [check["id"] for check in checks if applicability.get(check["id"]) == "applicable"]
    unknown = [check["id"] for check in checks if applicability.get(check["id"]) == "unknown"]
    not_applicable = [check["id"] for check in checks if applicability.get(check["id"]) == "not_applicable"]
    reported = [finding["id"] for finding in findings]
    missing = [check_id for check_id in applicable if check_id not in reported]
    unresolved_classification = classification["selected_variant"] is None
    return {
        "applicable_finding_ids": applicable,
        "reported_finding_ids": reported,
        "missing_applicable_finding_ids": missing,
        "unknown_finding_ids": unknown,
        "not_applicable_finding_ids": not_applicable,
        "classification_unresolved": unresolved_classification,
        "complete": not missing and not unknown and not unresolved_classification,
    }


def _cache_components(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": f"{CONTRACT_ID}:{CONTRACT_VERSION}",
        "engine": f"{ENGINE_ID}:{ENGINE_VERSION}",
        "startup_id": report["startup_id"],
        "source_snapshot": {"sha256": _digest(report["source_snapshot"])},
        "methodology": {
            "id": report["methodology"]["id"],
            "version": report["methodology"]["version"],
            "sha256": _digest(report["methodology"]),
        },
        "classification": {"sha256": _digest(report["classification"])},
        "evidence": {"sha256": _digest(report["evidence"])},
        "finding_producer": {
            "id": report["finding_producer"]["id"],
            "version": report["finding_producer"]["version"],
            "config_sha256": _digest(report["finding_producer"]["config"]),
            "payload_sha256": _digest({"producer": report["finding_producer"], "findings": report["findings"]}),
        },
        "selected_variant": report["classification"]["selected_variant"],
        "schema": SCHEMA_ID,
        "renderer": RENDERER_ID,
    }


def _content_components(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": f"{CONTRACT_ID}:{CONTRACT_VERSION}",
        "engine": f"{ENGINE_ID}:{ENGINE_VERSION}",
        "startup_id": report["startup_id"],
        "source_snapshot": {
            "startup_id": report["source_snapshot"]["startup_id"],
            "scope_id": report["source_snapshot"]["scope_id"],
            "sha256": _digest(report["source_snapshot"]),
        },
        "methodology": {
            "id": report["methodology"]["id"],
            "version": report["methodology"]["version"],
            "sha256": _digest(report["methodology"]),
        },
        "classification": {
            "sha256": _digest(report["classification"]),
            "provenance": report["classification"]["provenance"],
        },
        "evidence": {"sha256": _digest(report["evidence"])},
        "finding_producer": {
            "id": report["finding_producer"]["id"],
            "version": report["finding_producer"]["version"],
            "config_sha256": _digest(report["finding_producer"]["config"]),
            "payload_sha256": _digest({"producer": report["finding_producer"], "findings": report["findings"]}),
        },
        "selected_variants": {
            "requested": report["classification"]["requested_variant"],
            "selected": report["classification"]["selected_variant"],
        },
        "findings": report["findings"],
        "completeness": report["completeness"],
        "sections": report["sections"],
        "schema": SCHEMA_ID,
        "renderer": RENDERER_ID,
    }


def _identity(report: dict[str, Any]) -> dict[str, Any]:
    cache_components = _cache_components(report)
    content_components = _content_components(report)
    return {
        "cache": {"key": _digest(cache_components), "components": cache_components},
        "content": {"sha256": _digest(content_components), "components": content_components},
    }


def build_assessment(
    startup_id: str,
    source_snapshot: Mapping[str, Any],
    methodology: Mapping[str, Any],
    classification: Mapping[str, Any],
    evidence: list[Mapping[str, Any]],
    findings: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic report from supplied values only."""
    normalized_startup_id = _startup_id(startup_id)
    normalized_snapshot = _source_snapshot(source_snapshot)
    if normalized_snapshot["startup_id"] != normalized_startup_id:
        raise _error("source_snapshot.startup_id", "does not match startup_id")
    normalized_methodology = _methodology(methodology)
    normalized_evidence = _evidence(evidence, normalized_snapshot, normalized_startup_id)
    evidence_by_id = {item["id"]: item for item in normalized_evidence}
    normalized_classification, checks = _classification(
        classification,
        normalized_methodology,
        set(evidence_by_id),
    )
    producer, normalized_findings = _findings(
        findings,
        checks=checks,
        evidence_ids=set(evidence_by_id),
        applicability=normalized_classification["applicability"],
        allow_unreferenced=normalized_methodology["policy"]["evidence_reference_policy"]["allow_unreferenced"],
        additional_referenced_evidence_ids={
            evidence_id
            for decision in normalized_classification["applicability_decisions"].values()
            for evidence_id in decision["evidence_ids"]
        } | set(normalized_classification["evidence_ids"]),
    )
    completeness = _completeness(checks, normalized_classification, normalized_findings)
    sections = _build_sections(checks, normalized_classification, normalized_findings, evidence_by_id)
    report = {
        "contract": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "engine": ENGINE_ID,
        "engine_version": ENGINE_VERSION,
        "startup_id": normalized_startup_id,
        "identity": {"cache": {"key": "pending", "components": {}}, "content": {"sha256": "pending", "components": {}}},
        "methodology": normalized_methodology,
        "classification": normalized_classification,
        "source_snapshot": normalized_snapshot,
        "finding_producer": producer,
        "evidence": normalized_evidence,
        "findings": normalized_findings,
        "completeness": completeness,
        "sections": sections,
    }
    report["identity"] = _identity(report)
    validate_report(report)
    return report


def _validate_sections(
    report: dict[str, Any],
    checks: list[dict[str, Any]],
    classification: dict[str, Any],
    findings: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> None:
    evidence_by_id = {item["id"]: item for item in evidence}
    expected = _build_sections(checks, classification, findings, evidence_by_id)
    if report["sections"] != expected:
        raise _error("report.sections", "does not match reconstructed methodology/findings content")


def validate_report(report: object) -> None:
    """Validate and reconstruct every persisted report identity component."""
    value = _object(report, "report")
    _schema_validate(value, "report.schema.json", "report")
    expected_keys = {
        "contract", "contract_version", "engine", "engine_version", "startup_id", "identity",
        "methodology", "classification", "source_snapshot", "finding_producer", "evidence",
        "findings", "completeness", "sections",
    }
    _keys(value, path="report", required=expected_keys, allowed=expected_keys)
    if value["contract"] != CONTRACT_ID or value["contract_version"] != CONTRACT_VERSION:
        raise _error("report.contract", "unsupported report contract")
    if value["engine"] != ENGINE_ID or value["engine_version"] != ENGINE_VERSION:
        raise _error("report.engine", "unsupported engine identity")
    startup_id = _startup_id(value["startup_id"])
    snapshot = _source_snapshot(value["source_snapshot"], canonical=True)
    if snapshot["startup_id"] != startup_id:
        raise _error("report.source_snapshot.startup_id", "does not match report.startup_id")
    methodology = _methodology(value["methodology"], canonical=True)
    evidence = _evidence(value["evidence"], snapshot, startup_id, canonical=True)
    classification, checks = _classification(
        value["classification"],
        methodology,
        {item["id"] for item in evidence},
        canonical=True,
    )
    producer, findings = _findings(
        {"producer": value["finding_producer"], "items": value["findings"]},
        checks=checks,
        evidence_ids={item["id"] for item in evidence},
        applicability=classification["applicability"],
        allow_unreferenced=methodology["policy"]["evidence_reference_policy"]["allow_unreferenced"],
        additional_referenced_evidence_ids={
            evidence_id
            for decision in classification["applicability_decisions"].values()
            for evidence_id in decision["evidence_ids"]
        } | set(classification["evidence_ids"]),
        canonical=True,
    )
    if value["methodology"] != methodology:
        raise _error("report.methodology", "does not match reconstructed methodology")
    if value["classification"] != classification:
        raise _error("report.classification", "does not match reconstructed classification")
    if value["source_snapshot"] != snapshot:
        raise _error("report.source_snapshot", "does not match reconstructed snapshot")
    if value["evidence"] != evidence:
        raise _error("report.evidence", "does not match reconstructed evidence")
    if value["finding_producer"] != producer or value["findings"] != findings:
        raise _error("report.findings", "does not match reconstructed producer/findings")
    expected_completeness = _completeness(checks, classification, findings)
    if value["completeness"] != expected_completeness:
        raise _error("report.completeness", "does not match reconstructed completeness")
    _validate_sections(value, checks, classification, findings, evidence)
    expected_identity = _identity({
        **value,
        "methodology": methodology,
        "classification": classification,
        "source_snapshot": snapshot,
        "evidence": evidence,
        "finding_producer": producer,
        "findings": findings,
        "completeness": expected_completeness,
    })
    if value["identity"] != expected_identity:
        raise _error("report.identity", "does not match reconstructed report content")
    _json_value(value, "report")


def _markdown_text(value: str) -> str:
    text = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    for character in "\\`*_[]<>#|":
        text = text.replace(character, "\\" + character)
    return text


def render_assessment_markdown(report: Mapping[str, Any]) -> str:
    """Render a canonical report deterministically in four stable sections."""
    validate_report(report)
    lines = [f"# Jury assessment briefing: {_markdown_text(report['startup_id'])}", ""]
    classification = report["classification"]
    lines.extend([
        "**Classification**",
        "",
        f"* Label: {_markdown_text(classification['label'])}",
        f"* Confidence: {_markdown_text(classification['confidence'])}",
        f"* Uncertain: {'yes' if classification['uncertain'] else 'no'}",
    ])
    if classification["ambiguity_reason"]:
        lines.append(f"* Ambiguity reason: {_markdown_text(classification['ambiguity_reason'])}")
    lines.append("")
    for section in report["sections"]:
        lines.extend([f"## {_markdown_text(section['name'])}", "", f"**Section state:** {section['state']}", "", _markdown_text(section["summary"]), ""])
        for check in section["checks"]:
            lines.extend([
                f"### {_markdown_text(check['label'])} (`{_markdown_text(check['id'])}`)",
                "",
                f"* Applicability: {_markdown_text(check['applicability'])}",
                f"* State: {_markdown_text(check['state'])}",
                f"* Summary: {_markdown_text(check['summary'])}",
            ])
            if check["follow_up_questions"]:
                lines.append("* Follow-up questions:")
                lines.extend(f"  * {_markdown_text(question)}" for question in check["follow_up_questions"])
            else:
                lines.append("* Follow-up questions: none supplied.")
            if check["evidence"]:
                lines.append("* Evidence excerpts:")
                lines.extend(f"  * {_markdown_text(excerpt)}" for excerpt in check["evidence"])
            else:
                lines.append("* Evidence excerpts: none supplied.")
            lines.append("")
        lines.extend(["**Questions for the jury**", ""])
        if section["jury_questions"]:
            lines.extend(f"* {_markdown_text(question)}" for question in section["jury_questions"])
        else:
            lines.append("* None supplied by this deterministic core.")
        lines.append("")
    return "\n".join(lines).strip()

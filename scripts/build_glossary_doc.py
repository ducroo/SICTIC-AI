"""Validate and render the public glossary source.

``config/glossary/glossary.json`` is authoritative.  ``docs/GLOSSARY.md`` is
generated from it and must never become a second source of truth.  Validation
is deliberately fail-closed: stale public references, duplicate identifiers,
unknown contract types, and incomplete producer/consumer contracts stop the
build before documentation is written.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "config" / "glossary" / "glossary.json"
TARGET = REPO_ROOT / "docs" / "GLOSSARY.md"

_PUBLIC_ROOTS = {"config", "lib", "scripts", "skills", "tests"}
_ROOT_FIELDS = {
    "schema_version",
    "visibility",
    "source_of_truth",
    "description",
    "generated_document",
    "supported_contracts",
    "terms",
    "metric_contracts",
}
_REFERENCE_FIELDS = {"path", "symbol"}
_TERM_FIELDS = {"id", "term", "definition", "references"}
_CONTRACT_FIELDS = {"id", "contract", "metric", "producer", "consumers"}
_ENDPOINT_FIELDS = {"reference", "path", "type"}
_SUPPORTED_CONTRACTS = {
    "audit-v2": 2,
    "metric-v1": 1,
}
_SUPPORTED_ENDPOINT_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)


def _reference_parts(reference: str) -> tuple[str, str | None]:
    path, separator, symbol = reference.partition("::")
    return path, symbol if separator else None


def _check_fields(value: dict[str, Any], allowed: set[str], location: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{location} has a non-textual property name")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{location} has unsupported properties")
    missing = allowed - set(value)
    if missing:
        raise ValueError(f"{location} is missing required properties")


def _text(
    value: Any,
    location: str,
    *,
    allow_empty: bool = False,
    allow_newlines: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{location} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{location} must not be empty")
    if any(
        (ord(character) < 32 and not (allow_newlines and character in "\r\n\t"))
        or ord(character) == 127
        for character in value
    ):
        raise ValueError(f"{location} contains a control character")
    return value


def _normalize_repo_path(path: Any, location: str) -> str:
    path = _text(path, location)
    candidate = path.strip().replace("\\", "/")
    posix = PurePosixPath(candidate)
    windows = PureWindowsPath(candidate)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(f"{location} must be a repository-relative path")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{location} contains a non-canonical path component")
    normalized = "/".join(parts)
    if normalized.split("/", 1)[0] not in _PUBLIC_ROOTS:
        raise ValueError(f"{location} is outside the public source tree")
    return normalized


def validate_rendered_document(document: str) -> None:
    """Validate the generic textual contract of the generated document."""
    _text(document, "rendered document", allow_newlines=True)


def _declared_python_symbols(path: Path) -> set[str]:
    """Collect names actually bound at a Python module's top level."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        raise ValueError(f"stale public reference: invalid Python file {path}") from error

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _check_reference(reference: dict[str, Any], *, repo_root: Path) -> str:
    _check_fields(reference, _REFERENCE_FIELDS, "public reference")
    path = _normalize_repo_path(reference["path"], "public reference path")
    resolved = (repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError(f"reference escapes the repository: {path}") from error
    if not resolved.is_file():
        raise ValueError(f"stale public reference: {path}")
    symbol = reference["symbol"]
    if symbol is not None:
        symbol = _text(symbol, f"public reference symbol")
        if not symbol.isidentifier() or resolved.suffix != ".py":
            raise ValueError(f"reference has a non-importable symbol: {path}::{symbol}")
        if symbol not in _declared_python_symbols(resolved):
            raise ValueError(f"stale public reference: {path}::{symbol}")
    return path


def _check_contract_endpoint(endpoint: dict[str, Any], *, repo_root: Path) -> None:
    _check_fields(endpoint, _ENDPOINT_FIELDS, "metric contract endpoint")
    reference = _text(endpoint["reference"], "metric contract endpoint reference")
    if "::" not in reference:
        raise ValueError("metric contract endpoints need a path::symbol reference")
    path, symbol = _reference_parts(reference)
    _check_reference({"path": path, "symbol": symbol}, repo_root=repo_root)
    _text(endpoint["path"], f"metric contract endpoint data path")
    value_type = endpoint.get("type")
    if not isinstance(value_type, list) or not value_type:
        raise ValueError(f"metric contract endpoint has no concrete type: {reference}")
    if not all(
        isinstance(item, str)
        and not any(ord(character) < 32 or ord(character) == 127 for character in item)
        and item in _SUPPORTED_ENDPOINT_TYPES
        for item in value_type
    ):
        raise ValueError(f"unsupported metric endpoint type: {reference}")


def validate_source(source: dict[str, Any], *, repo_root: Path = REPO_ROOT) -> None:
    """Validate the public dictionary/matrix before rendering it."""
    _check_fields(source, _ROOT_FIELDS, "glossary")
    if source["schema_version"] != 1 or type(source["schema_version"]) is not int:
        raise ValueError("unsupported glossary schema version")
    _text(source["visibility"], "visibility")
    _text(source["description"], "description")
    _text(source["generated_document"], "generated_document")
    if not isinstance(source["source_of_truth"], bool):
        raise ValueError("source_of_truth must be boolean")
    if source.get("visibility") != "public" or source.get("source_of_truth") is not True:
        raise ValueError("glossary must explicitly be the authoritative public source")
    if source.get("generated_document") != "docs/GLOSSARY.md":
        raise ValueError("glossary must name docs/GLOSSARY.md as its generated view")

    terms = source.get("terms")
    contracts = source.get("metric_contracts")
    if not isinstance(terms, list) or not isinstance(contracts, list):
        raise ValueError("glossary terms and metric_contracts must be lists")
    supported_contracts = source["supported_contracts"]
    _check_fields(supported_contracts, set(_SUPPORTED_CONTRACTS), "supported_contracts")
    if supported_contracts != _SUPPORTED_CONTRACTS:
        raise ValueError("unsupported public contract type declaration")

    identifiers: list[str] = []
    for term in terms:
        _check_fields(term, _TERM_FIELDS, "glossary term")
        term_id = _text(term["id"], "glossary term id")
        _text(term["term"], f"glossary term {term_id} term")
        _text(term["definition"], f"glossary term {term_id} definition")
        identifiers.append(term_id)
        references = term["references"]
        if not isinstance(references, list) or not references:
            raise ValueError(f"glossary term has no public references: {term_id}")
        for reference in references:
            _check_reference(reference, repo_root=repo_root)

    for contract in contracts:
        _check_fields(contract, _CONTRACT_FIELDS, "metric contract")
        contract_id = _text(contract["id"], "metric contract id")
        contract_type = _text(contract["contract"], f"metric contract {contract_id} type")
        metric = _text(contract["metric"], f"metric contract {contract_id} metric")
        identifiers.append(contract_id)
        if contract_type not in supported_contracts:
            raise ValueError(f"unsupported public contract: {contract_type}")
        if metric not in {term["id"] for term in terms}:
            raise ValueError(f"metric contract names an unknown metric: {metric}")
        _check_contract_endpoint(contract["producer"], repo_root=repo_root)
        consumers = contract["consumers"]
        if not isinstance(consumers, list) or not consumers:
            raise ValueError(f"metric contract has no consumers: {contract_id}")
        for consumer in consumers:
            _check_contract_endpoint(consumer, repo_root=repo_root)
            if consumer["path"] != contract["producer"]["path"]:
                raise ValueError(
                    f"metric contract path mismatch: {contract_id}"
                )
            if consumer["type"] != contract["producer"]["type"]:
                raise ValueError(
                    f"metric contract type mismatch: {contract_id}"
                )

    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate glossary or metric-contract identifier")


def _render_reference(reference: str) -> str:
    path, symbol = _reference_parts(reference)
    normalized = _normalize_repo_path(path, "public reference path")
    return f"{normalized}{'::' + symbol if symbol else ''}"


def _render_reference_object(reference: dict[str, Any]) -> str:
    normalized = _normalize_repo_path(reference["path"], "public reference path")
    symbol = reference["symbol"]
    return f"{normalized}{'::' + symbol if symbol else ''}"


def render(source: dict[str, Any]) -> str:
    """Render a validated source deterministically."""
    validate_source(source)
    lines = [
        "# Public glossary",
        "",
        "<!-- Generated from config/glossary/glossary.json by "
        "scripts/build_glossary_doc.py. Do not edit by hand. -->",
        "",
        source["description"],
        "",
        "## Source contract",
        "",
        "- **Visibility:** public",
        "- **Authoritative source:** `config/glossary/glossary.json`",
        "- **Generated view:** `docs/GLOSSARY.md`",
        "- **Source boundary:** only public interfaces are included; derived checklists are not authoritative.",
        "",
        "## Dictionary",
        "",
        "| identifier | term | definition | public references |",
        "|---|---|---|---|",
    ]
    for term in source["terms"]:
        refs = ", ".join(
            f"`{_render_reference_object(ref)}`"
            for ref in term["references"]
        )
        definition = term["definition"].replace("|", "\\|")
        lines.append(f"| `{term['id']}` | `{term['term']}` | {definition} | {refs} |")

    lines += [
        "",
        "## Metric contract matrix",
        "",
        "Each row states what a public producer emits and what public consumers accept.",
        "",
        "| identifier | metric | contract | producer | consumers |",
        "|---|---|---|---|---|",
    ]
    for contract in source["metric_contracts"]:
        producer = contract["producer"]
        producer_text = (
            f"`{_render_reference(producer['reference'])}` (`{producer['path']}`, "
            f"{', '.join(producer['type'])})"
        )
        consumers = "<br>".join(
            f"`{_render_reference(consumer['reference'])}` (`{consumer['path']}`, "
            f"{', '.join(consumer['type'])})"
            for consumer in contract["consumers"]
        )
        lines.append(
            f"| `{contract['id']}` | `{contract['metric']}` | "
            f"`{contract['contract']}` | {producer_text} | {consumers} |"
        )
    lines += ["", "_This document is generated; edit the JSON source instead._", ""]
    document = "\n".join(lines)
    validate_rendered_document(document)
    return document


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    validate_source(source)
    TARGET.write_text(render(source), encoding="utf-8")
    print(f"{TARGET.relative_to(REPO_ROOT)}: glossary rendered")


if __name__ == "__main__":
    main()

"""Compose persisted artifact contracts from the canonical extraction schemas."""
from __future__ import annotations

from typing import Any

from lib.captable.cla_terms import build_cla_schema
from lib.infrastructure.ai_text_generation.json import copy_schema, validate_json_schema
from lib.infrastructure.configuration import load_repository_config


def build_artifact_schema(identifier: str) -> dict[str, Any]:
    config = load_repository_config("captable_build")
    definitions = copy_schema(config["artifact_schemas"])
    responses = {
        "classification": config["classification_response_schema"],
        "cla": build_cla_schema(config)["schema"],
        "captable": config["captable_extraction_response_schema"],
        "register": config["register_extraction_response_schema"],
        "pool": config["pool_extraction_response_schema"],
    }
    for name, response in responses.items():
        schema = copy_schema(response)
        metadata = ["dataset"] if name == "classification" else ["dataset", "document"]
        schema["properties"].update({field: {"type": "string"} for field in metadata})
        schema["required"] = [*schema["required"], *metadata]
        # CLA schemas use local $defs references, which must retain their own root.
        schema.setdefault("$id", f"urn:sictic:captable-build:{name}")
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        definitions[name] = schema
    if identifier not in {"classification", *config["artifact_schemas"]}:
        raise ValueError(f"Unknown captable_build artifact: {identifier!r}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{identifier}",
        "$defs": definitions,
    }


def validate_build_artifact(data: Any, identifier: str) -> None:
    validate_json_schema(data, build_artifact_schema(identifier), label=f"Captable {identifier}")

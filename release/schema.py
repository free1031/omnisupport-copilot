"""JSON Schema validation for Week14 governed release manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "release"
    / "release_manifest_v2.schema.json"
)
CANARY_DECISION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "release"
    / "canary_decision.schema.json"
)


def validate_instance(value: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(value)


def validate_manifest_schema(
    manifest: dict[str, Any], schema_path: Path = DEFAULT_SCHEMA_PATH
) -> None:
    validate_instance(manifest, schema_path)


def validate_canary_decision(decision: dict[str, Any]) -> None:
    validate_instance(decision, CANARY_DECISION_SCHEMA_PATH)

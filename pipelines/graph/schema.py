"""Load and enforce the Week13 entity/relation schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.yaml")


@dataclass(frozen=True)
class GraphSchema:
    version: str
    entity_types: dict[str, dict[str, Any]]
    relation_types: dict[str, dict[str, Any]]
    quality_gate: dict[str, Any]

    @property
    def min_entity_confidence(self) -> float:
        return float(self.quality_gate["min_entity_confidence"])

    @property
    def min_relation_confidence(self) -> float:
        return float(self.quality_gate["min_relation_confidence"])

    @property
    def fuzzy_auto_merge_threshold(self) -> float:
        return float(self.quality_gate["fuzzy_auto_merge_threshold"])

    @property
    def fuzzy_review_threshold(self) -> float:
        return float(self.quality_gate["fuzzy_review_threshold"])

    @property
    def max_query_hops(self) -> int:
        return int(self.quality_gate["max_query_hops"])

    def validate_entity_type(self, entity_type: str) -> None:
        if entity_type not in self.entity_types:
            raise ValueError(f"entity type is not allowlisted: {entity_type}")

    def validate_relation(self, relation_type: str, source_type: str, target_type: str) -> None:
        spec = self.relation_types.get(relation_type)
        if spec is None:
            raise ValueError(f"relation type is not allowlisted: {relation_type}")
        if source_type not in spec["source_types"] or target_type not in spec["target_types"]:
            raise ValueError(
                f"invalid relation endpoints: {source_type}-[{relation_type}]->{target_type}"
            )

    def alias_map(self, entity_type: str) -> dict[str, str]:
        from pipelines.graph.align import normalize_name

        aliases: dict[str, str] = {}
        for canonical, values in self.entity_types.get(entity_type, {}).get("aliases", {}).items():
            aliases[normalize_name(canonical)] = canonical
            for value in values:
                aliases[normalize_name(str(value))] = canonical
        return aliases


def load_graph_schema(path: Path | str = DEFAULT_SCHEMA_PATH) -> GraphSchema:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    required = {"version", "entity_types", "relation_types", "quality_gate"}
    missing = required - set(data or {})
    if missing:
        raise ValueError(f"graph schema missing fields: {', '.join(sorted(missing))}")
    schema = GraphSchema(
        version=str(data["version"]),
        entity_types=dict(data["entity_types"]),
        relation_types=dict(data["relation_types"]),
        quality_gate=dict(data["quality_gate"]),
    )
    for relation_type, spec in schema.relation_types.items():
        for key in ("source_types", "target_types"):
            if not spec.get(key):
                raise ValueError(f"{relation_type} must declare {key}")
            for entity_type in spec[key]:
                schema.validate_entity_type(entity_type)
    if not 1 <= schema.max_query_hops <= 3:
        raise ValueError("max_query_hops must be between 1 and 3")
    return schema

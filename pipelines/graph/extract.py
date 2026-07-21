"""Schema-constrained extraction for evidence-ready chunks.

The baseline extractor is deterministic and accepts reviewed annotations or
high-precision `Type: value` lines. A production LLM/NER adapter can implement
the same protocol, but its output must pass this validator before alignment.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

from pipelines.graph.models import (
    EntityMention,
    ExtractionResult,
    RelationMention,
    SourceChunk,
)
from pipelines.graph.schema import GraphSchema

FIELD_TYPES = {
    "product": "PRODUCT",
    "issue": "ISSUE",
    "symptom": "SYMPTOM",
    "resolution": "RESOLUTION",
    "version": "VERSION",
}
RELATION_CHAIN = (
    ("PRODUCT", "HAS_ISSUE", "ISSUE"),
    ("ISSUE", "HAS_SYMPTOM", "SYMPTOM"),
    ("ISSUE", "RESOLVED_BY", "RESOLUTION"),
    ("RESOLUTION", "APPLIES_TO_VERSION", "VERSION"),
)
MAX_ENTITY_NAME_LENGTH = 256


class Extractor(Protocol):
    def extract(self, chunk: SourceChunk, schema: GraphSchema) -> ExtractionResult: ...


class SchemaConstrainedExtractor:
    def extract(self, chunk: SourceChunk, schema: GraphSchema) -> ExtractionResult:
        if chunk.annotations:
            return self._from_annotations(chunk, schema)
        return self._from_labeled_text(chunk, schema)

    def _from_annotations(self, chunk: SourceChunk, schema: GraphSchema) -> ExtractionResult:
        entities = []
        relations = []
        warnings: list[str] = []
        for raw in chunk.annotations.get("entities", []):
            try:
                entity_type = str(raw["type"]).upper()
                schema.validate_entity_type(entity_type)
                confidence = _confidence(raw.get("confidence", 1.0))
                if confidence < schema.min_entity_confidence:
                    warnings.append(f"low_confidence_entity:{entity_type}:{raw.get('name', '')}")
                    continue
                entities.append(
                    EntityMention(
                        entity_type=entity_type,
                        name=_required_name(raw["name"], "entity.name"),
                        confidence=confidence,
                        chunk_id=chunk.chunk_id,
                        evidence_id=chunk.evidence_id,
                        properties=dict(raw.get("properties") or {}),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                warnings.append(f"invalid_entity:{exc}")
        for raw in chunk.annotations.get("relations", []):
            try:
                relation_type = str(raw["type"]).upper()
                source_type = str(raw["source_type"]).upper()
                target_type = str(raw["target_type"]).upper()
                schema.validate_relation(relation_type, source_type, target_type)
                confidence = _confidence(raw.get("confidence", 1.0))
                if confidence < schema.min_relation_confidence:
                    warnings.append(f"low_confidence_relation:{relation_type}")
                    continue
                relations.append(
                    RelationMention(
                        relation_type=relation_type,
                        source_type=source_type,
                        source_name=_required_name(raw["source"], "relation.source"),
                        target_type=target_type,
                        target_name=_required_name(raw["target"], "relation.target"),
                        confidence=confidence,
                        chunk_id=chunk.chunk_id,
                        evidence_id=chunk.evidence_id,
                        properties=dict(raw.get("properties") or {}),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                warnings.append(f"invalid_relation:{exc}")
        return ExtractionResult(tuple(entities), tuple(relations), tuple(warnings))

    def _from_labeled_text(self, chunk: SourceChunk, schema: GraphSchema) -> ExtractionResult:
        values: dict[str, str] = {}
        for line in chunk.content.splitlines():
            match = re.match(r"^\s*([A-Za-z]+)\s*[:：]\s*(.+?)\s*$", line)
            if match and match.group(1).lower() in FIELD_TYPES:
                values[FIELD_TYPES[match.group(1).lower()]] = match.group(2)
        entities = [
            EntityMention(
                entity_type=entity_type,
                name=_required_name(name, "entity.name"),
                confidence=0.96,
                chunk_id=chunk.chunk_id,
                evidence_id=chunk.evidence_id,
            )
            for entity_type, name in values.items()
        ]
        relations = []
        for source_type, relation_type, target_type in RELATION_CHAIN:
            if source_type in values and target_type in values:
                schema.validate_relation(relation_type, source_type, target_type)
                relations.append(
                    RelationMention(
                        relation_type=relation_type,
                        source_type=source_type,
                        source_name=values[source_type],
                        target_type=target_type,
                        target_name=values[target_type],
                        confidence=0.95,
                        chunk_id=chunk.chunk_id,
                        evidence_id=chunk.evidence_id,
                    )
                )
        warnings = () if entities else ("no_schema_constrained_entities",)
        return ExtractionResult(tuple(entities), tuple(relations), warnings)


def _confidence(raw: object) -> float:
    value = float(raw)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("confidence must be finite and in [0, 1]")
    return value


def _required_name(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{field} must be a non-empty string")
    value = raw.strip()
    if len(value) > MAX_ENTITY_NAME_LENGTH:
        raise ValueError(f"{field} exceeds {MAX_ENTITY_NAME_LENGTH} characters")
    return value

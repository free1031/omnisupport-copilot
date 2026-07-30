"""Dependency-light domain models for graph construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    evidence_id: str
    doc_id: str
    source_id: str
    content: str
    data_release_id: str
    product_line: str = "any"
    visibility_scope: str = "internal"
    annotations: dict[str, Any] = field(default_factory=dict)
    section_path: str = ""
    page_no: int | None = None
    title: str | None = None
    bbox: str | None = None
    source_url: str | None = None
    doc_version: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SourceChunk":
        required = [
            "chunk_id",
            "evidence_id",
            "doc_id",
            "source_id",
            "content",
            "data_release_id",
        ]
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f"source chunk missing required fields: {', '.join(missing)}")
        return cls(
            chunk_id=str(data["chunk_id"]),
            evidence_id=str(data["evidence_id"]),
            doc_id=str(data["doc_id"]),
            source_id=str(data["source_id"]),
            content=str(data["content"]),
            data_release_id=str(data["data_release_id"]),
            product_line=str(data.get("product_line") or "any"),
            visibility_scope=str(data.get("visibility_scope") or "internal"),
            annotations=dict(data.get("annotations") or {}),
            section_path=str(data.get("section_path") or ""),
            page_no=int(data["page_no"]) if data.get("page_no") is not None else None,
            title=str(data["title"]) if data.get("title") is not None else None,
            bbox=str(data["bbox"]) if data.get("bbox") is not None else None,
            source_url=str(data["source_url"]) if data.get("source_url") is not None else None,
            doc_version=(
                str(data["doc_version"]) if data.get("doc_version") is not None else None
            ),
        )


@dataclass(frozen=True)
class EntityMention:
    entity_type: str
    name: str
    confidence: float
    chunk_id: str
    evidence_id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationMention:
    relation_type: str
    source_type: str
    source_name: str
    target_type: str
    target_name: str
    confidence: float
    chunk_id: str
    evidence_id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionResult:
    entities: tuple[EntityMention, ...]
    relations: tuple[RelationMention, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlignmentDecision:
    entity_id: str
    entity_type: str
    canonical_name: str
    normalized_name: str
    status: str
    reason: str
    confidence: float


@dataclass
class GraphEntity:
    entity_id: str
    graph_release_id: str
    entity_type: str
    canonical_name: str
    normalized_name: str
    aliases: set[str] = field(default_factory=set)
    properties: dict[str, Any] = field(default_factory=dict)
    chunk_ids: set[str] = field(default_factory=set)
    evidence_ids: set[str] = field(default_factory=set)
    data_release_id: str = ""
    product_line: str = "any"
    visibility_scope: str = "internal"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("aliases", "chunk_ids", "evidence_ids"):
            data[key] = sorted(data[key])
        return data


@dataclass
class GraphEdge:
    edge_id: str
    graph_release_id: str
    relation_type: str
    source_entity_id: str
    target_entity_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    chunk_ids: set[str] = field(default_factory=set)
    evidence_ids: set[str] = field(default_factory=set)
    data_release_id: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["chunk_ids"] = sorted(data["chunk_ids"])
        data["evidence_ids"] = sorted(data["evidence_ids"])
        return data


@dataclass(frozen=True)
class GraphCommunity:
    community_id: str
    graph_release_id: str
    level: int
    member_entity_ids: tuple[str, ...]
    summary: str
    evidence_ids: tuple[str, ...]
    product_lines: tuple[str, ...]
    visibility_scopes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["member_entity_ids"] = list(self.member_entity_ids)
        for key in ("evidence_ids", "product_lines", "visibility_scopes"):
            data[key] = list(data[key])
        return data


@dataclass
class GraphBuildResult:
    graph_release_id: str
    graph_schema_version: str
    data_release_ids: set[str]
    entities: list[GraphEntity]
    edges: list[GraphEdge]
    communities: list[GraphCommunity]
    source_chunk_count: int
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return (
            "pass"
            if self.entities and self.edges and not self.quarantined and not self.rejected
            else "warn"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "graph_build_report_v1",
            "graph_release_id": self.graph_release_id,
            "graph_schema_version": self.graph_schema_version,
            "data_release_ids": sorted(self.data_release_ids),
            "status": self.status,
            "source_chunk_count": self.source_chunk_count,
            "entity_count": len(self.entities),
            "edge_count": len(self.edges),
            "community_count": len(self.communities),
            "quarantined_count": len(self.quarantined),
            "rejected_count": len(self.rejected),
            "entities": [item.to_dict() for item in self.entities],
            "edges": [item.to_dict() for item in self.edges],
            "communities": [item.to_dict() for item in self.communities],
            "quarantined": self.quarantined,
            "rejected": self.rejected,
            "warnings": self.warnings,
        }

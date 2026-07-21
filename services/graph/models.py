"""Runtime models shared by graph stores and retrieval strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RetrievalMode = Literal[
    "hybrid",
    "auto",
    "graph_local",
    "graph_global",
    "graph_multihop",
    "graph_drift",
]


@dataclass(frozen=True)
class RouteDecision:
    mode: RetrievalMode
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GraphEntityRecord:
    entity_id: str
    entity_type: str
    canonical_name: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    product_line: str = "any"
    visibility_scope: str = "internal"


@dataclass(frozen=True)
class GraphRelationRecord:
    edge_id: str
    relation_type: str
    source_entity_id: str
    target_entity_id: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphPathRecord:
    entities: tuple[GraphEntityRecord, ...]
    relations: tuple[GraphRelationRecord, ...]
    score: float

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        values = {value for item in self.entities for value in item.evidence_ids}
        values.update(value for item in self.relations for value in item.evidence_ids)
        return tuple(sorted(values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [asdict(item) for item in self.entities],
            "relations": [asdict(item) for item in self.relations],
            "score": self.score,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class GraphCommunityRecord:
    community_id: str
    summary: str
    member_count: int
    evidence_ids: tuple[str, ...]
    score: float
    product_lines: tuple[str, ...] = ()
    visibility_scopes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphEvidenceChunk:
    chunk_id: str
    evidence_id: str
    doc_id: str
    source_id: str
    content: str
    section_path: str
    page_no: int | None = None
    title: str | None = None
    bbox: str | None = None
    source_url: str | None = None
    doc_version: str | None = None
    final_score: float = 0.0
    vector_score: float | None = None
    fts_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    product_line: str = "any"
    visibility_scope: str = "internal"

    def debug_scores(self) -> dict[str, float | None]:
        return {
            "graph_score": self.final_score,
            "vector_score": self.vector_score,
            "fts_score": self.fts_score,
            "rrf_score": self.rrf_score,
            "rerank_score": self.rerank_score,
        }


@dataclass
class GraphRetrievalResult:
    mode: RetrievalMode
    graph_release_id: str
    route_confidence: float
    route_reasons: tuple[str, ...]
    paths: list[GraphPathRecord] = field(default_factory=list)
    communities: list[GraphCommunityRecord] = field(default_factory=list)
    chunks: list[GraphEvidenceChunk] = field(default_factory=list)
    serialized_context: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def evidence_ids(self) -> list[str]:
        return sorted({chunk.evidence_id for chunk in self.chunks})

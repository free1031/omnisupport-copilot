"""Build a versioned graph artifact from evidence-ready chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from pipelines.graph.align import EntityAligner, normalize_name
from pipelines.graph.community import build_communities
from pipelines.graph.extract import Extractor, SchemaConstrainedExtractor
from pipelines.graph.models import GraphBuildResult, GraphEdge, GraphEntity, SourceChunk
from pipelines.graph.schema import GraphSchema, load_graph_schema


def build_graph(
    chunks: list[SourceChunk],
    *,
    graph_release_id: str,
    schema: GraphSchema | None = None,
    extractor: Extractor | None = None,
) -> GraphBuildResult:
    if not graph_release_id.strip():
        raise ValueError("graph_release_id is required")
    if not chunks:
        raise ValueError("at least one source chunk is required")
    _validate_source_identities(chunks)
    schema = schema or load_graph_schema()
    extractor = extractor or SchemaConstrainedExtractor()
    aligner = EntityAligner(schema)
    entities: dict[str, GraphEntity] = {}
    edges: dict[tuple[str, str, str], GraphEdge] = {}
    decisions: dict[tuple[str, str], str] = {}
    quarantined: list[dict] = []
    rejected: list[dict] = []
    warnings: list[str] = []

    for chunk in chunks:
        namespace = f"{chunk.product_line}:{chunk.visibility_scope}"
        result = extractor.extract(chunk, schema)
        for warning in result.warnings:
            warnings.append(f"{chunk.chunk_id}:{warning}")
            if warning.startswith("invalid_"):
                rejected.append(
                    {"kind": "extraction", "chunk_id": chunk.chunk_id, "reason": warning}
                )
        for mention in result.entities:
            if (
                not mention.name.strip()
                or len(mention.name) > 256
                or not math.isfinite(mention.confidence)
                or not 0 <= mention.confidence <= 1
            ):
                rejected.append(
                    {
                        "kind": "entity",
                        "chunk_id": chunk.chunk_id,
                        "entity_type": mention.entity_type,
                        "reason": "invalid_entity_payload",
                    }
                )
                continue
            decision = aligner.align(mention, namespace=namespace)
            key = (namespace, mention.entity_type, normalize_name(mention.name))
            if decision.status != "accepted":
                target = quarantined if decision.status == "quarantined" else rejected
                target.append(
                    {
                        "kind": "entity",
                        "chunk_id": chunk.chunk_id,
                        "entity_type": mention.entity_type,
                        "name": mention.name,
                        "reason": decision.reason,
                    }
                )
                continue
            decisions[key] = decision.entity_id
            entity = entities.get(decision.entity_id)
            if entity is None:
                entity = GraphEntity(
                    entity_id=decision.entity_id,
                    graph_release_id=graph_release_id,
                    entity_type=decision.entity_type,
                    canonical_name=decision.canonical_name,
                    normalized_name=decision.normalized_name,
                    data_release_id=chunk.data_release_id,
                    product_line=chunk.product_line,
                    visibility_scope=chunk.visibility_scope,
                    confidence=mention.confidence,
                )
                entities[entity.entity_id] = entity
            entity.aliases.add(mention.name)
            entity.chunk_ids.add(chunk.chunk_id)
            entity.evidence_ids.add(chunk.evidence_id)
            entity.properties.update(mention.properties)
            entity.confidence = max(entity.confidence, mention.confidence)

        for relation in result.relations:
            if (
                not relation.source_name.strip()
                or not relation.target_name.strip()
                or len(relation.source_name) > 256
                or len(relation.target_name) > 256
                or not math.isfinite(relation.confidence)
                or not 0 <= relation.confidence <= 1
            ):
                rejected.append(
                    {
                        "kind": "relation",
                        "relation_type": relation.relation_type,
                        "chunk_id": chunk.chunk_id,
                        "reason": "invalid_relation_payload",
                    }
                )
                continue
            source_id = decisions.get(
                (namespace, relation.source_type, normalize_name(relation.source_name))
            )
            target_id = decisions.get(
                (namespace, relation.target_type, normalize_name(relation.target_name))
            )
            if not relation.evidence_id:
                rejected.append({"kind": "relation", "reason": "missing_evidence", "chunk_id": chunk.chunk_id})
                continue
            if not source_id or not target_id:
                quarantined.append(
                    {
                        "kind": "relation",
                        "relation_type": relation.relation_type,
                        "chunk_id": chunk.chunk_id,
                        "reason": "unaligned_endpoint",
                    }
                )
                continue
            schema.validate_relation(relation.relation_type, relation.source_type, relation.target_type)
            edge_key = (source_id, relation.relation_type, target_id)
            edge = edges.get(edge_key)
            if edge is None:
                digest = hashlib.sha256(
                    f"{graph_release_id}:{source_id}:{relation.relation_type}:{target_id}".encode()
                ).hexdigest()[:24]
                edge = GraphEdge(
                    edge_id=f"edge-{digest}",
                    graph_release_id=graph_release_id,
                    relation_type=relation.relation_type,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    data_release_id=chunk.data_release_id,
                    confidence=relation.confidence,
                )
                edges[edge_key] = edge
            edge.chunk_ids.add(relation.chunk_id)
            edge.evidence_ids.add(relation.evidence_id)
            edge.properties.update(relation.properties)
            edge.confidence = max(edge.confidence, relation.confidence)

    entity_list = sorted(entities.values(), key=lambda item: item.entity_id)
    edge_list = sorted(edges.values(), key=lambda item: item.edge_id)
    communities = build_communities(graph_release_id, entity_list, edge_list)
    return GraphBuildResult(
        graph_release_id=graph_release_id,
        graph_schema_version=schema.version,
        data_release_ids={chunk.data_release_id for chunk in chunks},
        entities=entity_list,
        edges=edge_list,
        communities=communities,
        source_chunk_count=len(chunks),
        quarantined=quarantined,
        rejected=rejected,
        warnings=warnings,
    )


def load_chunks(path: Path) -> list[SourceChunk]:
    chunks = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            chunks.append(SourceChunk.from_mapping(json.loads(line)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return chunks


def _validate_source_identities(chunks: list[SourceChunk]) -> None:
    for field in ("chunk_id", "evidence_id"):
        seen: set[str] = set()
        duplicates: set[str] = set()
        for chunk in chunks:
            value = getattr(chunk, field)
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        if duplicates:
            raise ValueError(f"duplicate {field}: {', '.join(sorted(duplicates))}")
    release_ids = {chunk.data_release_id for chunk in chunks}
    if len(release_ids) != 1:
        raise ValueError(
            "a graph release must be built from exactly one data_release_id; "
            f"received {', '.join(sorted(release_ids))}"
        )


def build_graph_from_jsonl(path: Path, *, graph_release_id: str) -> GraphBuildResult:
    return build_graph(load_chunks(path), graph_release_id=graph_release_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Week13 governed graph artifact")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--graph-release-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/week13/graph-build-report.json"))
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--index-release-id", default=os.getenv("WEEK08_INDEX_RELEASE_ID"))
    args = parser.parse_args(argv)
    chunks = load_chunks(args.input)
    result = build_graph(chunks, graph_release_id=args.graph_release_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.persist:
        if not args.database_url:
            raise SystemExit("--database-url or DATABASE_URL is required with --persist")
        from pipelines.graph.store import persist_graph_build

        persist_graph_build(
            args.database_url,
            result,
            chunks,
            index_release_id=args.index_release_id,
        )
    print(json.dumps({
        "status": result.status,
        "graph_release_id": result.graph_release_id,
        "entities": len(result.entities),
        "edges": len(result.edges),
        "communities": len(result.communities),
        "report_path": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

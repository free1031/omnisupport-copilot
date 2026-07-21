"""Bounded graph-to-text serialization for grounded generation."""

from __future__ import annotations

from services.graph.models import GraphCommunityRecord, GraphPathRecord


def serialize_graph_context(
    paths: list[GraphPathRecord],
    communities: list[GraphCommunityRecord],
    *,
    max_chars: int = 6000,
    allowed_evidence_ids: set[str] | None = None,
) -> str:
    blocks: list[str] = []
    for index, path in enumerate(paths, 1):
        if allowed_evidence_ids is not None and any(
            not (set(relation.evidence_ids) & allowed_evidence_ids)
            for relation in path.relations
        ):
            continue
        parts = [path.entities[0].canonical_name]
        for relation, entity in zip(path.relations, path.entities[1:]):
            parts.append(f"-[{relation.relation_type}]-> {entity.canonical_name}")
        evidence_ids = set(path.evidence_ids)
        if allowed_evidence_ids is not None:
            evidence_ids &= allowed_evidence_ids
        evidence = ", ".join(sorted(evidence_ids))
        blocks.append(f"Path {index}: {' '.join(parts)}\nEvidence: {evidence}")
    for index, community in enumerate(communities, 1):
        evidence_ids = set(community.evidence_ids)
        if allowed_evidence_ids is not None:
            evidence_ids &= allowed_evidence_ids
            if not evidence_ids:
                continue
        evidence = ", ".join(sorted(evidence_ids))
        blocks.append(
            f"Community {index} ({community.member_count} entities): {community.summary}\n"
            f"Evidence: {evidence}"
        )
    value = "\n\n".join(blocks)
    return value[:max_chars]

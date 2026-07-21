"""Deterministic Student Core community detection and summaries."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque

from pipelines.graph.models import GraphCommunity, GraphEdge, GraphEntity


def build_communities(
    graph_release_id: str,
    entities: list[GraphEntity],
    edges: list[GraphEdge],
) -> list[GraphCommunity]:
    by_id = {entity.entity_id: entity for entity in entities}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source_entity_id].add(edge.target_entity_id)
        adjacency[edge.target_entity_id].add(edge.source_entity_id)

    communities: list[GraphCommunity] = []
    unseen = set(by_id)
    while unseen:
        root = min(unseen)
        queue = deque([root])
        members: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in members:
                continue
            members.add(current)
            unseen.discard(current)
            queue.extend(sorted(adjacency[current] - members))
        member_ids = tuple(sorted(members))
        evidence_ids = tuple(sorted({eid for member in member_ids for eid in by_id[member].evidence_ids}))
        digest = hashlib.sha256("|".join(member_ids).encode()).hexdigest()[:20]
        communities.append(
            GraphCommunity(
                community_id=f"community-{digest}",
                graph_release_id=graph_release_id,
                level=0,
                member_entity_ids=member_ids,
                summary=_summary([by_id[member] for member in member_ids]),
                evidence_ids=evidence_ids,
                product_lines=tuple(sorted({by_id[member].product_line for member in member_ids})),
                visibility_scopes=tuple(
                    sorted({by_id[member].visibility_scope for member in member_ids})
                ),
            )
        )
    return sorted(communities, key=lambda item: item.community_id)


def _summary(entities: list[GraphEntity]) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for entity in sorted(entities, key=lambda item: (item.entity_type, item.canonical_name)):
        grouped[entity.entity_type].append(entity.canonical_name)
    parts = [f"{entity_type}: {', '.join(names[:8])}" for entity_type, names in sorted(grouped.items())]
    return "; ".join(parts)
